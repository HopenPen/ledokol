"""Классификатор кассового разрыва, версия 2: признаки по известным платежам и больше обучающих окон.

Что нового по сравнению с gap_classifier.py:
1. Прогноз гибрида и список ожидаемых платежей (регулярные, налоги) считаются для окон с шагом 4 дня по всей истории,
   параллельно на всех ядрах. Из них признаки: сколько обязательных платежей придётся на ближайшие h дней и каким будет
   запас на счёте после них.
2. Два режима обучения. «по времени»: обучающие окна заканчиваются раньше первого проверочного (самый строгий).
   «по компаниям»: обучение на всех окнах других компаний, как в обычной кросс-валидации по группам.
   В обоих режимах компании из теста в обучении не участвуют.
3. Усреднение двух обучений с разными зёрнами.
4. Выборка сохраняется в experiments/out/gap_v2_dataset.parquet для TabPFN (experiments/gap_tabpfn.py).

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml python experiments/gap_classifier_v2.py
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))

H, STEP_EVAL, N_EVAL, MIN_HIST, SEED, STEP_TRAIN = 30, 5, 12, 60, 7, 4
HS = [5, 10, 20, 30]
OUT = "experiments/out"
CACHE = f"{OUT}/hyb_v2.pkl"


def compute_company(args):
    """В отдельном процессе: для компании считаем прогноз гибрида и сумму ожидаемых платежей на каждую нужную дату."""
    cid, df, ts = args
    sys.path.insert(0, os.path.abspath("../backend"))
    from app.domain.forecast import fit, forecast
    from app.domain.pipeline import prepare_company
    prep = prepare_company(df)
    panel, ops = prep.panel.reset_index(drop=True), prep.ops
    out = {}
    for t in ts:
        cutoff = panel.loc[t, "date"]
        m = fit(ops[ops["operation_date"].le(cutoff)], panel.iloc[: t + 1])
        res = forecast(m, [], horizon=H, n_sims=150, seed=SEED)
        day_idx = {p.day: i for i, p in enumerate(res.points)}
        out_cum, in_cum = np.zeros(H), np.zeros(H)
        for e in res.events:
            i = day_idx.get(e.event_date)
            if i is None:
                continue
            if e.direction.value == "out":
                out_cum[i:] += e.amount
            else:
                in_cum[i:] += e.amount * e.probability
        out[(cid, t)] = {"bal": float(panel.loc[t, "balance"]),
                         "arr": np.array([[p.p10, p.p50, p.p90, p.prob_below] for p in res.points], dtype=np.float32),
                         "out": out_cum.astype(np.float32), "inn": in_cum.astype(np.float32)}
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    from catboost import CatBoostClassifier, Pool
    from sklearn.metrics import (average_precision_score, f1_score, precision_recall_curve, precision_score,
                                 recall_score, roc_auc_score)
    from sklearn.model_selection import StratifiedGroupKFold

    from app.domain.categories import EXCLUDED_FROM_FORECAST
    from app.domain.ingest import read_statement
    from app.domain.ml_flow import operational_flow, scale_of
    from app.domain.pipeline import prepare_company, split_by_company

    root = os.environ["CASE_DIR"]
    raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
    companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
    INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
    by_company = split_by_company(raw)
    preps = {cid: prepare_company(df) for cid, df in by_company.items()}

    C = {}
    for cid, p in preps.items():
        ops, panel = p.ops, p.panel.reset_index(drop=True)
        bal = panel["balance"].to_numpy(dtype=float)
        owner_in = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["direction"].eq("in")].groupby("operation_date")["amount"].sum()
        inj = panel["date"].map(owner_in).fillna(0.0).to_numpy()
        flow = operational_flow(p).to_numpy(dtype=float)
        C[cid] = {"days": pd.DatetimeIndex(panel["date"]), "bal": bal, "inj": inj, "flow": flow, "cum": np.r_[0.0, np.cumsum(flow)],
                  "gapday": (bal < 0) | ((inj > 0) & (bal - inj < 0)), "after_gap": panel["after_gap"].to_numpy(),
                  "cuminj": np.r_[0.0, np.cumsum(inj > 0)]}

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

    # --- кеш гибрида: считаем только недостающее, параллельно ---
    cache = pickle.load(open(CACHE, "rb")) if os.path.exists(CACHE) else {}
    train_ts = {cid: [t for t in range(MIN_HIST, len(d["bal"]) - 1, STEP_TRAIN) if t + H < len(d["bal"])] for cid, d in C.items()}
    jobs = []
    for cid in C:
        need = sorted({t for t in train_ts[cid] + eval_pos[cid] if (cid, t) not in cache})
        if need:
            jobs.append((cid, by_company[cid], need))
    t0 = time.time()
    if jobs:
        print(f"гибрид: нужно посчитать {sum(len(j[2]) for j in jobs):,} окон по {len(jobs)} компаниям, процессов 10", flush=True)
        with ProcessPoolExecutor(max_workers=10) as ex:
            for k, part in enumerate(ex.map(compute_company, jobs)):
                cache.update(part)
                if k % 30 == 29:
                    print(f"  готово компаний: {k + 1}/{len(jobs)}, {time.time() - t0:.0f} с", flush=True)
        pickle.dump(cache, open(CACHE, "wb"))
    print(f"кеш гибрида: {len(cache):,} окон, {time.time() - t0:.0f} с", flush=True)

    def row(cid: str, t: int, h: int) -> dict | None:
        d = C[cid]
        n = len(d["bal"])
        if t + h >= n or d["bal"][t] < 0 or d["after_gap"][t + 1: t + h + 1].any() or (cid, t) not in cache:
            return None
        e = cache[(cid, t)]
        sc = scale_of(d["flow"][max(0, t - 59): t + 1])
        h_n = d["flow"][: t + 1] / sc
        p10, p50, prob = e["arr"][:h, 0], e["arr"][:h, 1], e["arr"][:h, 3]
        bal0 = d["bal"][t]
        cushion = bal0 / sc
        out_h, in_h = e["out"][h - 1] / sc, e["inn"][h - 1] / sc
        lagy = (d["cum"][t - 252 + h + 1] - d["cum"][t - 252 + 1]) / sc if t - 252 >= 0 else np.nan
        return {
            "company": cid, "t": t, "h": h, "industry": INDUSTRY.get(cid, "unknown"), "end_date": d["days"][min(t + h, n - 1)],
            "cushion": cushion, "min_bal_60": d["bal"][max(0, t - 59): t + 1].min() / sc, "bal_trend_20": (bal0 - d["bal"][max(0, t - 20)]) / sc,
            "inj_events_180": float(d["cuminj"][t + 1] - d["cuminj"][max(0, t - 179)]),
            "inj_amount_180": d["inj"][max(0, t - 179): t + 1].sum() / sc,
            "mean_5": h_n[-5:].mean(), "mean_20": h_n[-20:].mean(), "mean_60": h_n[-60:].mean(), "std_20": h_n[-20:].std(),
            "share_pos_20": (h_n[-20:] > 0).mean(), "lag_year": lagy,
            "known_out": out_h, "known_in": in_h, "cushion_after_out": cushion - out_h, "cushion_after_net": cushion - out_h + in_h,
            "hyb_pmax": prob.max(), "hyb_pmean": prob.mean(), "hyb_first_day": int(np.argmax(prob >= 0.2)) + 1 if (prob >= 0.2).any() else h + 1,
            "hyb_min_p10": p10.min() / sc, "hyb_min_p50": p50.min() / sc, "hyb_end_p50": (p50[-1] - bal0) / sc,
            "y": int(d["gapday"][t + 1: t + h + 1].any()),
        }

    rows = []
    for cid in C:
        for t in train_ts[cid]:
            for h in HS:
                r = row(cid, t, h)
                if r:
                    rows.append({**r, "is_eval": 0})
        for t in eval_pos[cid]:
            for h in HS:
                r = row(cid, t, h)
                if r:
                    rows.append({**r, "is_eval": 1})
    DS = pd.DataFrame(rows)
    DS["fold"] = DS["company"].map(fold_of)
    DS.to_parquet(f"{OUT}/gap_v2_dataset.parquet")
    print(f"выборка: {len(DS):,} строк, из них проверочных {int(DS['is_eval'].sum()):,}; сохранена", flush=True)

    STATS = ["industry", "h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180", "mean_5", "mean_20", "mean_60",
             "std_20", "share_pos_20", "lag_year"]
    EVENTS = ["known_out", "known_in", "cushion_after_out", "cushion_after_net"]
    HYB = ["hyb_pmax", "hyb_pmean", "hyb_first_day", "hyb_min_p10", "hyb_min_p50", "hyb_end_p50"]
    SETS = {"без гибрида и без известных платежей": STATS, "+ известные платежи": STATS + EVENTS, "+ известные платежи и прогноз гибрида": STATS + EVENTS + HYB}
    PLAN = [("по компаниям", name) for name in SETS] + [("по времени", "+ известные платежи и прогноз гибрида")]

    def fit_cls(tr, va, feats, seed):
        m = CatBoostClassifier(iterations=1000, learning_rate=0.05, depth=6, l2_leaf_reg=6, random_seed=seed, eval_metric="AUC",
                               od_type="Iter", od_wait=80, use_best_model=True, verbose=False, thread_count=-1)
        m.fit(Pool(tr[feats], tr["y"], cat_features=["industry"]), eval_set=Pool(va[feats], va["y"], cat_features=["industry"]))
        return m

    rng = np.random.default_rng(SEED)
    scores = []
    for f in range(5):
        tr_ids = [c for c in ids if fold_of[c] != f]
        v_ids = set(rng.choice(tr_ids, size=int(len(tr_ids) * 0.15), replace=False))
        te = DS[(DS["is_eval"] == 1) & (DS["fold"] == f)]
        for mode, name in PLAN:
            pool = DS[(DS["is_eval"] == 0) & DS["company"].isin(tr_ids)]
            if mode == "по времени":
                pool = pool[pool["end_date"] < EVAL_START]
            trn, val = pool[~pool["company"].isin(v_ids)], pool[pool["company"].isin(v_ids)]
            sc = np.mean([fit_cls(trn, val, SETS[name], s).predict_proba(te[SETS[name]])[:, 1] for s in (7, 42)], axis=0)
            scores.append(te[["company", "t", "h", "y", "fold"]].assign(mode=mode, набор=name, score=sc))
        print(f"фолд {f}: обучение «по компаниям» {len(DS[(DS['is_eval'] == 0) & DS['company'].isin(tr_ids)]):,} строк", flush=True)
    SC = pd.concat(scores, ignore_index=True)
    SC.to_parquet(f"{OUT}/gap_v2_scores.parquet")

    GRID = np.round(np.arange(0.03, 0.96, 0.02), 2)

    def nested(df):
        pred = np.zeros(len(df), dtype=bool)
        for f in sorted(df["fold"].unique()):
            other, mine = df["fold"].ne(f), df["fold"].eq(f)
            best = max(GRID, key=lambda t: f1_score(df.loc[other, "y"], df.loc[other, "score"] >= t))
            pred[mine.to_numpy()] = df.loc[mine, "score"].to_numpy() >= best
        return pred

    def tradeoff(df):
        p, r, _ = precision_recall_curve(df["y"], df["score"])
        res = {}
        for target in (0.6, 0.7, 0.8, 0.9):
            mask = r[:-1] >= target
            res[str(target)] = round(float(p[int(np.argmax(np.where(mask, p[:-1], -1)))]), 3)
        return res

    report = {}
    for mode, name in PLAN:
        key = f"{mode} | {name}"
        report[key] = {}
        for h in HS:
            d = SC[(SC["mode"] == mode) & (SC["набор"] == name) & (SC["h"] == h)].reset_index(drop=True)
            pred = nested(d)
            report[key][h] = {"ROC-AUC": round(roc_auc_score(d["y"], d["score"]), 3), "PR-AUC": round(average_precision_score(d["y"], d["score"]), 3),
                              "precision": round(precision_score(d["y"], pred), 3), "recall": round(recall_score(d["y"], pred), 3),
                              "F1": round(f1_score(d["y"], pred), 3), "precision при recall": tradeoff(d)}
    json.dump(report, open(f"{OUT}/gap_classifier_v2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for key, v in report.items():
        print(f"\n=== {key}")
        print(pd.DataFrame({h: {k: x for k, x in r.items() if k != "precision при recall"} for h, r in v.items()}).T.to_string())
        print("   компромисс на 30 днях (precision при recall 0.6/0.7/0.8/0.9):", v[30]["precision при recall"])


if __name__ == "__main__":
    main()
