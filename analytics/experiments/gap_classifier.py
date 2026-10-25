"""CatBoost-классификатор, обученный напрямую на метку «в ближайшие h рабочих дней будет кассовый разрыв».

Чем отличается от модели в ноутбуке: там вероятность разрыва получалась косвенно, из квантилей прогноза суммы потока, и
модель вообще не знала, насколько остаток близок к нулю. Здесь признаки:
  запас на счёте (остаток в дневных оборотах, минимум за 60 дней, динамика), частота прошлых «докладываний» денег
  владельцем (так видны скрытые разрывы), статистика потока, поток за тот же период год назад, прогноз гибрида
  (вероятность разрыва, минимум коридора) и горизонт h.
Проверка та же: 5 фолдов по компаниям (те же группы, что в ноутбуке), обучение только на окнах, которые закончились раньше
первого проверочного, те же проверочные окна, порог для фолда подбирается по остальным фолдам. Результат — experiments/out/gap_classifier.json.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml --with matplotlib python experiments/gap_classifier.py
"""
from __future__ import annotations

import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

from catboost import CatBoostClassifier, Pool  # noqa: E402
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score  # noqa: E402
from sklearn.model_selection import StratifiedGroupKFold  # noqa: E402

from app.domain.categories import EXCLUDED_FROM_FORECAST  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import operational_flow, scale_of  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

H, STEP_EVAL, N_EVAL, MIN_HIST, SEED = 30, 5, 12, 60, 7
HS = [5, 10, 20, 30]
OUT = "experiments/out"

root = os.environ["CASE_DIR"]
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
preps = {cid: prepare_company(df) for cid, df in sorted(split_by_company(raw).items())}
hyb = pickle.load(open(f"{OUT}/hybrid_cache.pkl", "rb"))          # прогнозы гибрида, посчитанные раньше в тех же точках

# --- по каждой компании: ряды, нужные для признаков и меток ---
C = {}
for cid, p in preps.items():
    ops, panel = p.ops, p.panel.reset_index(drop=True)
    days = pd.DatetimeIndex(panel["date"])
    bal = panel["balance"].to_numpy(dtype=float)
    owner_in = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["direction"].eq("in")].groupby("operation_date")["amount"].sum()
    inj = panel["date"].map(owner_in).fillna(0.0).to_numpy()
    flow = operational_flow(p)
    C[cid] = {"days": days, "bal": bal, "inj": inj, "flow": flow.to_numpy(dtype=float), "cum": np.r_[0.0, np.cumsum(flow.to_numpy(dtype=float))],
              "gapday": (bal < 0) | ((inj > 0) & (bal - inj < 0)), "after_gap": panel["after_gap"].to_numpy(),
              "cuminj": np.r_[0.0, np.cumsum(inj > 0)]}

# --- проверочные окна (как в ноутбуке) ---
eval_pos = {}
for cid, d in C.items():
    n = len(d["bal"])
    eval_pos[cid] = [pos for k in range(N_EVAL) if (pos := n - 1 - H - k * STEP_EVAL) >= MIN_HIST and not d["after_gap"][pos + 1: pos + 1 + H].any()]
EVAL_START = min(C[c]["days"][pos] for c in C for pos in eval_pos[c])
ids = np.array(sorted(preps))
fold_of = {}
for f, (_, te) in enumerate(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED).split(
        ids, [INDUSTRY.get(c, "unknown") for c in ids], groups=ids)):
    fold_of.update({c: f for c in ids[te]})


def row(cid: str, t: int, h: int) -> dict | None:
    """Признаки и метка для окна: компания, дата прогноза (индекс t), горизонт h. None — окно не годится."""
    d = C[cid]
    n = len(d["bal"])
    if t + h >= n or d["bal"][t] < 0 or d["after_gap"][t + 1: t + h + 1].any() or (cid, t) not in hyb:
        return None
    sc = scale_of(d["flow"][max(0, t - 59): t + 1])
    h_n = d["flow"][: t + 1] / sc
    _, arr = hyb[(cid, t)]
    p10, p50, prob = arr[:h, 0], arr[:h, 1], arr[:h, 3]
    bal0 = d["bal"][t]
    lagy = (d["cum"][t - 252 + h + 1] - d["cum"][t - 252 + 1]) / sc if t - 252 >= 0 else np.nan
    first = int(np.argmax(prob >= 0.2)) + 1 if (prob >= 0.2).any() else h + 1
    return {
        "company": cid, "t": t, "h": h, "industry": INDUSTRY.get(cid, "unknown"),
        "cushion": bal0 / sc, "min_bal_60": d["bal"][max(0, t - 59): t + 1].min() / sc, "bal_trend_20": (bal0 - d["bal"][max(0, t - 20)]) / sc,
        "inj_events_180": float(d["cuminj"][t + 1] - d["cuminj"][max(0, t - 179)]),
        "inj_amount_180": d["inj"][max(0, t - 179): t + 1].sum() / sc,
        "mean_5": h_n[-5:].mean(), "mean_20": h_n[-20:].mean(), "mean_60": h_n[-60:].mean(), "std_20": h_n[-20:].std(),
        "share_pos_20": (h_n[-20:] > 0).mean(), "lag_year": lagy,
        "hyb_pmax": prob.max(), "hyb_pmean": prob.mean(), "hyb_first_day": first,
        "hyb_min_p10": (p10.min() - 0) / sc, "hyb_min_p50": p50.min() / sc, "hyb_end_p50": (p50[-1] - bal0) / sc,
        "y": int(d["gapday"][t + 1: t + h + 1].any()),
    }


def build(cids, positions: dict | None) -> pd.DataFrame:
    rows = []
    for cid in cids:
        n = len(C[cid]["bal"])
        ts = positions[cid] if positions is not None else [t for t in range(MIN_HIST, n - 1, 6)
                                                            if t + H < n and C[cid]["days"][t + H] < EVAL_START]
        for t in ts:
            for h in HS:
                r = row(cid, t, h)
                if r:
                    rows.append(r)
    return pd.DataFrame(rows)


FEATS = ["industry", "h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180", "mean_5", "mean_20", "mean_60",
         "std_20", "share_pos_20", "lag_year", "hyb_pmax", "hyb_pmean", "hyb_first_day", "hyb_min_p10", "hyb_min_p50", "hyb_end_p50"]
SETS = {"только запас и история владельца": ["industry", "h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180"],
        "+ статистика потока и год назад": [c for c in FEATS if not c.startswith("hyb_")],
        "всё вместе (с прогнозом гибрида)": FEATS}


def fit_cls(tr, va, feats, seed=SEED):
    m = CatBoostClassifier(iterations=1000, learning_rate=0.05, depth=5, l2_leaf_reg=6, random_seed=seed, eval_metric="AUC",
                           od_type="Iter", od_wait=80, use_best_model=True, verbose=False, thread_count=-1)
    m.fit(Pool(tr[feats], tr["y"], cat_features=["industry"]), eval_set=Pool(va[feats], va["y"], cat_features=["industry"]))
    return m


rng = np.random.default_rng(SEED)
parts = {name: [] for name in SETS}
for f in range(5):
    tr_ids = [c for c in ids if fold_of[c] != f]
    v_ids = set(rng.choice(tr_ids, size=int(len(tr_ids) * 0.15), replace=False))
    trn = build([c for c in tr_ids if c not in v_ids], None)
    val = build([c for c in tr_ids if c in v_ids], None)
    te = build([c for c in ids if fold_of[c] == f], eval_pos)
    te["fold"] = f
    for name, feats in SETS.items():
        m = fit_cls(trn, val, feats)
        parts[name].append(te.assign(score=m.predict_proba(te[feats])[:, 1]))
    print(f"фолд {f}: обучение {len(trn):,} строк, тест {len(te):,}, доля разрывов в тесте {te['y'].mean():.2f}", flush=True)
RES = {name: pd.concat(v, ignore_index=True) for name, v in parts.items()}

GRID = np.round(np.arange(0.03, 0.96, 0.02), 2)


def nested(df):
    """Порог для каждого фолда выбираем по остальным фолдам (максимум F1)."""
    pred = np.zeros(len(df), dtype=bool)
    for f in sorted(df["fold"].unique()):
        other, mine = df["fold"].ne(f), df["fold"].eq(f)
        best = max(GRID, key=lambda t: f1_score(df.loc[other, "y"], df.loc[other, "score"] >= t))
        pred[mine.to_numpy()] = df.loc[mine, "score"].to_numpy() >= best
    return pred


def tradeoff(df):
    p, r, t = precision_recall_curve(df["y"], df["score"])
    out = {}
    for target in (0.6, 0.7, 0.8, 0.9):
        mask = r[:-1] >= target
        j = int(np.argmax(np.where(mask, p[:-1], -1)))
        out[str(target)] = round(float(p[j]), 3)
    return out


report = {}
for name, df in RES.items():
    report[name] = {}
    for h in HS:
        d = df[df["h"] == h].reset_index(drop=True)
        pred = nested(d)
        report[name][h] = {"окон": len(d), "доля разрывов": round(float(d["y"].mean()), 3), "ROC-AUC": round(roc_auc_score(d["y"], d["score"]), 3),
                           "PR-AUC": round(average_precision_score(d["y"], d["score"]), 3),
                           "precision": round(precision_score(d["y"], pred), 3), "recall": round(recall_score(d["y"], pred), 3),
                           "F1": round(f1_score(d["y"], pred), 3), "precision при recall>=": tradeoff(d)}
for name in SETS:
    print(f"\n=== {name}")
    print(pd.DataFrame({h: {k: v for k, v in report[name][h].items() if k != "precision при recall>="} for h in HS}).T.to_string())
best = RES["всё вместе (с прогнозом гибрида)"]
json.dump({"report": report, "features": FEATS, "note": "порог подобран вложенной кросс-валидацией по компаниям"},
          open(f"{OUT}/gap_classifier.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\nкомпромисс precision / recall для h=30 (всё вместе):", report["всё вместе (с прогнозом гибрида)"][30]["precision при recall>="])
# важность признаков последней модели не сохраняем: для отчёта достаточно сравнения наборов признаков
