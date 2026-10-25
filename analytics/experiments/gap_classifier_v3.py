"""Классификатор разрыва, версия 3: признаки про сезонные и крупные платежи, настройка параметров, смесь моделей.

Сравнивается с версией 2 на тех же окнах, тех же группах компаний и с теми же зёрнами:
  база       признаки v2 («+ известные платежи и прогноз гибрида»);
  расширенный база + что было в то же окно год назад, 21 и 63 дня назад, насколько крупные платежи бывали раньше,
              как давно был последний крупный платёж, календарь (число месяца, месяц);
  настроенный расширенный набор и параметры CatBoost из небольшой сетки (подбор внутри обучающих компаний);
  смесь       среднее вероятностей настроенного CatBoost, TabPFN и гибрида (если есть gap_tabpfn_scores.csv).
Порог для фолда подбирается по остальным фолдам. Результат — experiments/out/gap_classifier_v3.json.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml python experiments/gap_classifier_v3.py
"""
from __future__ import annotations

import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

from catboost import CatBoostClassifier, Pool  # noqa: E402
from sklearn.metrics import (average_precision_score, f1_score, precision_recall_curve, precision_score, recall_score,  # noqa: E402
                             roc_auc_score)

from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import operational_flow, scale_of  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

OUT = "experiments/out"
HS = [5, 10, 20, 30]
YEAR = 252                                            # рабочих дней в году

DS = pd.read_parquet(f"{OUT}/gap_v2_dataset.parquet")
raw = read_statement(open(os.path.join(os.environ["CASE_DIR"], "all_operations.csv"), "rb").read())
flows = {cid: operational_flow(prepare_company(df)).to_numpy(dtype=float) for cid, df in split_by_company(raw).items()}
days_all = {cid: operational_flow(prepare_company(df)).index for cid, df in split_by_company(raw).items()}


def extra_features(cid: str, t: int, h: int) -> dict:
    """Признаки из потока компании до даты прогноза t (будущее не используется)."""
    f = flows[cid]
    sc = scale_of(f[max(0, t - 59): t + 1])
    out = {}
    for name, lag in (("year", YEAR), ("m1", 21), ("m3", 63)):
        a = t - lag + 1
        if a >= 0 and t - lag + h <= t:               # окно целиком в прошлом
            w = f[a: a + h] / sc
            out[f"ly_{name}_net"], out[f"ly_{name}_min_day"] = w.sum(), w.min()
            out[f"ly_{name}_drawdown"] = np.cumsum(w).min()
        else:
            out[f"ly_{name}_net"] = out[f"ly_{name}_min_day"] = out[f"ly_{name}_drawdown"] = np.nan
    hist = f[: t + 1] / sc
    big = np.flatnonzero(hist < -8)                   # «крупный платёж»: день с чистым расходом больше 8 дневных оборотов
    out["big_out_count_365"] = float((hist[max(0, t - YEAR): t + 1] < -8).sum())
    out["days_since_big_out"] = float(t - big[-1]) if len(big) else np.nan
    out["max_out_day_180"] = float(hist[max(0, t - 179): t + 1].min())
    out["cutoff_dom"] = float(days_all[cid][t].day)
    out["cutoff_month"] = float(days_all[cid][t].month)
    return out


ex = pd.DataFrame([extra_features(c, t, h) for c, t, h in zip(DS["company"], DS["t"], DS["h"])], index=DS.index)
DS = pd.concat([DS, ex], axis=1)
print(f"выборка: {len(DS):,} строк, новых признаков: {ex.shape[1]}", flush=True)

STATS = ["industry", "h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180", "mean_5", "mean_20", "mean_60",
         "std_20", "share_pos_20", "lag_year"]
EVENTS = ["known_out", "known_in", "cushion_after_out", "cushion_after_net"]
HYB = ["hyb_pmax", "hyb_pmean", "hyb_first_day", "hyb_min_p10", "hyb_min_p50", "hyb_end_p50"]
BASE = STATS + EVENTS + HYB
EXTENDED = BASE + list(ex.columns)

GRID_PARAMS = [dict(depth=d, l2_leaf_reg=l2, learning_rate=lr) for d, l2, lr in
               itertools.product((4, 6, 8), (3, 10), (0.05,))]


def fit_cls(tr, va, feats, params, seed):
    m = CatBoostClassifier(iterations=1000, random_seed=seed, eval_metric="AUC", od_type="Iter", od_wait=80, use_best_model=True,
                           verbose=False, thread_count=-1, **params)
    m.fit(Pool(tr[feats], tr["y"], cat_features=["industry"]), eval_set=Pool(va[feats], va["y"], cat_features=["industry"]))
    return m


ids = np.array(sorted(DS["company"].unique()))
fold_of = DS.drop_duplicates("company").set_index("company")["fold"].to_dict()
rng = np.random.default_rng(7)
scores = []
chosen = []
for f in range(5):
    tr_ids = [c for c in ids if fold_of[c] != f]
    v_ids = set(rng.choice(tr_ids, size=int(len(tr_ids) * 0.15), replace=False))
    pool = DS[(DS["is_eval"] == 0) & DS["company"].isin(tr_ids)]
    trn, val = pool[~pool["company"].isin(v_ids)], pool[pool["company"].isin(v_ids)]
    te = DS[(DS["is_eval"] == 1) & (DS["fold"] == f)]
    # база и расширенный: параметры по умолчанию, два зерна
    for name, feats in (("база v2", BASE), ("расширенный", EXTENDED)):
        sc = np.mean([fit_cls(trn, val, feats, dict(depth=6, l2_leaf_reg=6, learning_rate=0.05), s).predict_proba(te[feats])[:, 1] for s in (7, 42)], axis=0)
        scores.append(te[["company", "t", "h", "y", "fold"]].assign(модель=name, score=sc))
    # настройка: лучшие параметры по AUC на проверочных компаниях (внутри обучающей части, тест не используется)
    best = max(GRID_PARAMS, key=lambda p: roc_auc_score(val["y"], fit_cls(trn, val, EXTENDED, p, 7).predict_proba(val[EXTENDED])[:, 1]))
    chosen.append(best)
    sc = np.mean([fit_cls(trn, val, EXTENDED, best, s).predict_proba(te[EXTENDED])[:, 1] for s in (7, 42)], axis=0)
    scores.append(te[["company", "t", "h", "y", "fold"]].assign(модель="расширенный + настройка", score=sc))
    print(f"фолд {f}: выбраны параметры {best}", flush=True)
SC = pd.concat(scores, ignore_index=True)

# смесь: настроенный CatBoost + TabPFN + гибрид (одинаковые окна по ключу компания, t, h)
tp_path = f"{OUT}/gap_tabpfn_scores.csv"
if os.path.exists(tp_path):
    tp = pd.read_csv(tp_path)[["company", "t", "h", "score"]].rename(columns={"score": "tabpfn"})
    cb = SC[SC["модель"] == "расширенный + настройка"].rename(columns={"score": "catboost"})[["company", "t", "h", "y", "fold", "catboost"]]
    hy = DS[DS["is_eval"] == 1][["company", "t", "h", "hyb_pmax"]]
    mix = cb.merge(tp, on=["company", "t", "h"]).merge(hy, on=["company", "t", "h"])
    for name, cols in (("смесь CatBoost + TabPFN", ["catboost", "tabpfn"]), ("смесь CatBoost + TabPFN + гибрид", ["catboost", "tabpfn", "hyb_pmax"])):
        SC = pd.concat([SC, mix[["company", "t", "h", "y", "fold"]].assign(модель=name, score=mix[cols].mean(axis=1))], ignore_index=True)
    SC = pd.concat([SC, mix[["company", "t", "h", "y", "fold"]].assign(модель="TabPFN (как в прошлый раз)", score=mix["tabpfn"])], ignore_index=True)
SC.to_parquet(f"{OUT}/gap_v3_scores.parquet")

GRID = np.round(np.arange(0.03, 0.96, 0.02), 2)


def nested(df):
    pred = np.zeros(len(df), dtype=bool)
    for f in sorted(df["fold"].unique()):
        other, mine = df["fold"].ne(f), df["fold"].eq(f)
        best = max(GRID, key=lambda t: f1_score(df.loc[other, "y"], df.loc[other, "score"] >= t))
        pred[mine.to_numpy()] = df.loc[mine, "score"].to_numpy() >= best
    return pred


report = {}
for name in SC["модель"].unique():
    report[name] = {}
    for h in HS:
        d = SC[(SC["модель"] == name) & (SC["h"] == h)].reset_index(drop=True)
        pred = nested(d)
        p, r, _ = precision_recall_curve(d["y"], d["score"])
        tr = {str(tg): round(float(p[int(np.argmax(np.where(r[:-1] >= tg, p[:-1], -1)))]), 3) for tg in (0.6, 0.7, 0.8, 0.9)}
        report[name][h] = {"ROC-AUC": round(roc_auc_score(d["y"], d["score"]), 3), "PR-AUC": round(average_precision_score(d["y"], d["score"]), 3),
                           "precision": round(precision_score(d["y"], pred), 3), "recall": round(recall_score(d["y"], pred), 3),
                           "F1": round(f1_score(d["y"], pred), 3), "precision при recall": tr}
json.dump({"report": report, "выбранные параметры по фолдам": chosen}, open(f"{OUT}/gap_classifier_v3.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
print("\n=== на 30 днях")
print(pd.DataFrame({n: {k: v for k, v in r[30].items() if k != "precision при recall"} for n, r in report.items()}).T.to_string())
for n, r in report.items():
    print(f"  {n}: precision при recall 0.6/0.7/0.8/0.9 = {r[30]['precision при recall']}")
