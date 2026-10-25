"""Эксперимент: регуляризация CatBoost и стекинг поверх гибрида (PBUSINES-TASK-2, TASK-1).

E0 — CatBoost v2 как в model_evaluation.ipynb;
E1 — то же с более сильной регуляризацией (переобучение на обучающие компании было в 1,1–1,6 раза);
E2 — E1 + прогноз гибрида как признаки: изменение остатка P10/P50/P90 и вероятность разрыва на горизонте h.
     Гибрид знает будущие регулярные платежи и налоги компании, CatBoost — опыт других компаний.

Протокол тот же, что в ноутбуке: 5 фолдов по компаниям, обучающие окна заканчиваются до первого проверочного,
порог предупреждения — вложенной кросс-валидацией. Результат — experiments/out/stacking.json.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml python experiments/catboost_stacking.py
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

from catboost import CatBoostRegressor, Pool  # noqa: E402
from scipy.stats import norm  # noqa: E402
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score  # noqa: E402
from sklearn.model_selection import StratifiedGroupKFold  # noqa: E402

from app.backtest.runner import _actual_gap_days  # noqa: E402
from app.domain.categories import EXCLUDED_FROM_FORECAST  # noqa: E402
from app.domain.forecast import fit, forecast  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import NON_FEATURES, make_cum_rows, mix_weights, operational_flow  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

H, STEP_EVAL, N_EVAL, MIN_HIST, TRAIN_STEP = 30, 5, 12, 60, 6
TRAIN_H = [1, 2, 3, 5, 7, 10, 14, 20, 25, 30]
QS = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]
SEED, N_SIMS = 7, 200
OUT = "experiments/out"
os.makedirs(OUT, exist_ok=True)

root = os.environ["CASE_DIR"]
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
preps = {cid: prepare_company(df) for cid, df in sorted(split_by_company(raw).items())}
flows = {c: operational_flow(p) for c, p in preps.items()}
gaps = {c: p.panel["after_gap"].to_numpy() for c, p in preps.items()}
print(f"компаний: {len(preps)}")

# --- проверочные окна (как в ноутбуке) ---
windows = []
for cid, prep in preps.items():
    panel, ops, n = prep.panel.reset_index(drop=True), prep.ops, len(prep.panel)
    excl = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["quality"].ne("duplicate")].groupby("operation_date")["signed"].sum()
    for k in range(N_EVAL):
        pos = n - 1 - H - k * STEP_EVAL
        if pos < MIN_HIST:
            break
        win = panel.iloc[pos + 1: pos + 1 + H]
        if win["after_gap"].any():
            continue
        hist = ops[ops["operation_date"].le(panel.loc[pos, "date"])]
        out_flow = hist[hist["direction"].eq("out") & hist["operation_date"].isin(panel["date"].iloc[:pos + 1].tail(60))]
        actual = win["balance"].to_numpy()
        windows.append({"company": cid, "industry": INDUSTRY.get(cid, "unknown"), "pos": pos, "cutoff": panel.loc[pos, "date"],
                        "bal0": float(panel.loc[pos, "balance"]),
                        "actual_oper": actual - np.cumsum(win["date"].map(excl).fillna(0.0).to_numpy()),
                        "scale": max(out_flow["amount"].sum() / 60, 1.0),
                        "gap_actual": bool(_actual_gap_days(win, ops).size), "ongoing": bool(panel.loc[pos, "balance"] < 0)})
W = pd.DataFrame(windows)
EVAL_START = W["cutoff"].min()

# --- прогноз гибрида для каждой нужной отсечки (кеш) ---
cache_path = f"{OUT}/hybrid_cache.pkl"
hyb = pickle.load(open(cache_path, "rb")) if os.path.exists(cache_path) else {}
need = []
for cid, prep in preps.items():
    n = len(prep.panel)
    need += [(cid, t) for t in range(MIN_HIST, n - 1, TRAIN_STEP) if prep.panel["date"].iloc[min(t + 1, n - 1)] < EVAL_START]
need += list(zip(W["company"], W["pos"]))
todo = [k for k in dict.fromkeys(need) if k not in hyb]
t0 = time.time()
for i, (cid, t) in enumerate(todo):
    prep = preps[cid]
    panel = prep.panel.reset_index(drop=True)
    cutoff = panel.loc[t, "date"]
    m = fit(prep.ops[prep.ops["operation_date"].le(cutoff)], panel.iloc[: t + 1])
    res = forecast(m, [], horizon=H, n_sims=N_SIMS, seed=SEED)
    hyb[(cid, t)] = (float(panel.loc[t, "balance"]),
                     np.array([[p.p10, p.p50, p.p90, p.prob_below] for p in res.points], dtype=np.float32))
    if i % 1000 == 999:
        print(f"гибрид: {i + 1}/{len(todo)} за {time.time() - t0:.0f} с")
        pickle.dump(hyb, open(cache_path, "wb"))
pickle.dump(hyb, open(cache_path, "wb"))
print(f"гибрид готов: {len(hyb)} отсечек, новых {len(todo)} за {time.time() - t0:.0f} с")


def add_hybrid(rows: pd.DataFrame, cid: str, flow: pd.Series) -> pd.DataFrame:
    """Признаки гибрида в тех же единицах, что цель: изменение остатка за h дней / масштаб."""
    pos = flow.index.get_indexer(rows["cutoff"])
    feats = []
    for t, h, sc in zip(pos, rows["h"], rows["scale"]):
        bal, arr = hyb[(cid, t)]
        p10, p50, p90, pb = arr[h - 1]
        feats.append(((p10 - bal) / sc, (p50 - bal) / sc, (p90 - bal) / sc, pb))
    return rows.assign(**dict(zip(["hyb_d10", "hyb_d50", "hyb_d90", "hyb_prob"], np.array(feats).T)))


def rows_for(cids, positions=None, stacked=False) -> pd.DataFrame:
    frames = []
    for c in cids:
        kw = {"positions": positions[c]} if positions else {"horizons": TRAIN_H, "max_target_date": EVAL_START}
        r = make_cum_rows(flows[c], INDUSTRY.get(c, "unknown"), step=TRAIN_STEP, min_history=MIN_HIST,
                          after_gap=gaps[c], company=c, **kw)
        if len(r):
            frames.append(add_hybrid(r, c, flows[c]) if stacked else r)
    return pd.concat(frames, ignore_index=True)


def X(df, force_case=False):
    x = df.drop(columns=[c for c in NON_FEATURES if c in df.columns])
    return x.assign(source="case") if force_case else x


def fit_cb(loss, tr, va, params):
    m = CatBoostRegressor(loss_function=loss, eval_metric=loss, iterations=1500, learning_rate=0.06, random_seed=SEED,
                          od_type="Iter", od_wait=100, use_best_model=True, verbose=False, thread_count=-1, **params)
    m.fit(Pool(X(tr), tr["y"], cat_features=["industry", "target_dow", "source"], weight=mix_weights(tr)),
          eval_set=Pool(X(va, True), va["y"], cat_features=["industry", "target_dow", "source"]))
    return m


def prob_below(q: np.ndarray, thr: float = 0.0) -> float:
    """Макс. по дням P(остаток < 0) из квантилей; за краями — нормальный хвост (без «ступеньки» в нуле)."""
    best = 0.0
    for row in q:
        if row[0] <= thr <= row[-1]:
            p = np.interp(thr, row, QS)
        else:
            sigma = max((row[-1] - row[0]) / (2 * norm.ppf(QS[-1])), 1e-9)
            p = norm.cdf((thr - row[QS.index(0.5)]) / sigma)
            p = min(p, QS[0]) if thr < row[0] else max(p, QS[-1])
        best = max(best, p)
    return best


ids = np.array(sorted(preps))
fold_of = {}
sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
for f, (_, te) in enumerate(sgkf.split(ids, [INDUSTRY.get(c, "unknown") for c in ids], groups=ids)):
    fold_of.update({c: f for c in ids[te]})
W["fold"] = W["company"].map(fold_of)
W["hyb_score"] = [hyb[(c, p)][1][:, 3].max() for c, p in zip(W["company"], W["pos"])]
W["hyb_p50"] = [hyb[(c, p)][1][:, 1] for c, p in zip(W["company"], W["pos"])]

EXPERIMENTS = {
    "E0 как в ноутбуке": ({"depth": 6, "l2_leaf_reg": 5.0}, False),
    "E1 регуляризация": ({"depth": 4, "l2_leaf_reg": 15.0, "rsm": 0.7, "random_strength": 2.0,
                         "bootstrap_type": "Bernoulli", "subsample": 0.7}, False),
    "E2 регуляризация + гибрид": ({"depth": 4, "l2_leaf_reg": 15.0, "rsm": 0.7, "random_strength": 2.0,
                                  "bootstrap_type": "Bernoulli", "subsample": 0.7}, True),
}
Q_LOSS = "MultiQuantile:alpha=" + ",".join(map(str, QS))
results, per_window = {}, {}
for name, (params, stacked) in EXPERIMENTS.items():
    t0 = time.time()
    score, mean_path, fold_rows = np.zeros(len(W)), [None] * len(W), []
    rng = np.random.default_rng(SEED)
    for f in range(5):
        train_ids = [c for c in ids if fold_of[c] != f]
        val_ids = set(rng.choice(train_ids, size=max(2, int(len(train_ids) * 0.15)), replace=False))
        allr = rows_for(train_ids, stacked=stacked)
        tr, va = allr[~allr["company"].isin(val_ids)], allr[allr["company"].isin(val_ids)]
        lo, hi = tr["y"].quantile([0.005, 0.995])
        tr, va = tr.assign(y=tr["y"].clip(lo, hi)), va.assign(y=va["y"].clip(lo, hi))
        m_mean, m_q = fit_cb("RMSE", tr, va, params), fit_cb(Q_LOSS, tr, va, params)
        idx = np.flatnonzero(W["fold"].eq(f))
        te = rows_for(sorted(set(W.loc[idx, "company"])), stacked=stacked,
                      positions={c: W.loc[idx][W.loc[idx, "company"].eq(c)]["pos"].tolist() for c in set(W.loc[idx, "company"])})
        te_y = te["y"].clip(lo, hi)
        pm, pq = np.asarray(m_mean.predict(X(te, True))), np.sort(np.asarray(m_q.predict(X(te, True))), axis=1)
        for i in idx:
            w = W.iloc[i]
            sel = (te["company"].eq(w["company"]) & te["cutoff"].eq(w["cutoff"])).to_numpy()
            sc = te.loc[sel, "scale"].iloc[0]
            mean_path[i] = w["bal0"] + sc * pm[sel]
            score[i] = prob_below(w["bal0"] + sc * pq[sel])
        rmse = lambda a, b: float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))  # noqa: E731
        fold_rows.append({"train": rmse(tr["y"], m_mean.predict(X(tr))), "val": rmse(va["y"], m_mean.predict(X(va, True))),
                          "test": rmse(te_y, pm), "trees": m_mean.tree_count_})
    per_window[name] = (score, mean_path)
    results[name] = {"folds": fold_rows, "секунд": round(time.time() - t0)}
    print(name, results[name])

# --- метрики на одних и тех же окнах ---
C = W[~W["ongoing"]].index.to_numpy()
y = W.loc[C, "gap_actual"].to_numpy()
GRID = np.round(np.arange(0.05, 0.96, 0.05), 2)


def nested_f1(s: np.ndarray) -> float:
    folds, pred = W.loc[C, "fold"].to_numpy(), np.zeros(len(C), dtype=bool)
    for f in range(5):
        best = max(GRID, key=lambda t: f1_score(y[folds != f], s[folds != f] >= t))
        pred[folds == f] = s[folds == f] >= best
    return f1_score(y, pred)


def rmse_h30(paths) -> float:
    e = [(p[29] - a[29]) / s for p, a, s in zip(paths, W["actual_oper"], W["scale"])]
    return float(np.sqrt(np.mean(np.square(e))))


summary = {}
candidates = {"Гибрид": (W["hyb_score"].to_numpy(), list(W["hyb_p50"]))}
for name, (score, paths) in per_window.items():
    candidates[name] = (score, paths)
    candidates[f"Ансамбль: гибрид + {name}"] = ((score + W["hyb_score"].to_numpy()) / 2,
                                               [(a + b) / 2 for a, b in zip(paths, W["hyb_p50"])])
for name, (score, paths) in candidates.items():
    s = score[C]
    summary[name] = {"ROC-AUC": roc_auc_score(y, s), "PR-AUC": average_precision_score(y, s), "F1 (вложенный порог)": nested_f1(s),
                     "RMSE h30": rmse_h30(paths)}
print(pd.DataFrame(summary).T.round(3).to_string())
json.dump({"summary": summary, "folds": results}, open(f"{OUT}/stacking.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
