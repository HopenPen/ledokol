"""TabPFN (готовая предобученная модель для небольших табличных данных) на задаче «будет ли разрыв».

Выборка и признаки те же, что в gap_classifier_v2.py (experiments/out/gap_v2_dataset.csv), группы компаний те же.
TabPFN обучается «в один проход» без подбора параметров, но принимает до ~10 000 строк, поэтому для каждого фолда берём
случайные 10 000 строк из обучающих компаний. Порог для фолда подбирается по остальным фолдам.
Запускать в окружении, где есть tabpfn и torch: python experiments/gap_tabpfn.py
"""
from __future__ import annotations

import json
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score
from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion

sys.stdout.reconfigure(encoding="utf-8")
OUT = "experiments/out"
STATS = ["h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180", "mean_5", "mean_20", "mean_60", "std_20",
         "share_pos_20", "lag_year"]
EVENTS = ["known_out", "known_in", "cushion_after_out", "cushion_after_net"]
HYB = ["hyb_pmax", "hyb_pmean", "hyb_first_day", "hyb_min_p10", "hyb_min_p50", "hyb_end_p50"]
FEATS = ["industry_code"] + STATS + EVENTS + HYB
HS = [5, 10, 20, 30]

DS = pd.read_csv(f"{OUT}/gap_v2_dataset.csv")
DS["industry_code"] = DS["industry"].astype("category").cat.codes
cat_idx = [FEATS.index("industry_code")]
rng = np.random.default_rng(7)
parts, t0 = [], time.time()
for f in range(5):
    train = DS[(DS["is_eval"] == 0) & (DS["fold"] != f)]
    train = train.sample(n=min(10000, len(train)), random_state=7)
    test = DS[(DS["is_eval"] == 1) & (DS["fold"] == f)]
    # явно берём веса v2: лицензия Apache 2.0 с указанием автора (новые версии весов некоммерческие)
    clf = TabPFNClassifier.create_default_for_version(ModelVersion.V2, device="cuda", categorical_features_indices=cat_idx, random_state=7, n_estimators=8)
    clf.fit(train[FEATS].to_numpy(dtype=float), train["y"].to_numpy())
    score = clf.predict_proba(test[FEATS].to_numpy(dtype=float))[:, 1]
    parts.append(test[["company", "t", "h", "y", "fold"]].assign(score=score))
    print(f"фолд {f}: обучение {len(train):,}, тест {len(test):,}, {time.time() - t0:.0f} с", flush=True)
SC = pd.concat(parts, ignore_index=True)
SC.to_csv(f"{OUT}/gap_tabpfn_scores.csv", index=False)

GRID = np.round(np.arange(0.03, 0.96, 0.02), 2)


def nested(df):
    pred = np.zeros(len(df), dtype=bool)
    for f in sorted(df["fold"].unique()):
        other, mine = df["fold"].ne(f), df["fold"].eq(f)
        best = max(GRID, key=lambda t: f1_score(df.loc[other, "y"], df.loc[other, "score"] >= t))
        pred[mine.to_numpy()] = df.loc[mine, "score"].to_numpy() >= best
    return pred


report = {}
for h in HS:
    d = SC[SC["h"] == h].reset_index(drop=True)
    pred = nested(d)
    p, r, _ = precision_recall_curve(d["y"], d["score"])
    trade = {str(tg): round(float(p[int(np.argmax(np.where(r[:-1] >= tg, p[:-1], -1)))]), 3) for tg in (0.6, 0.7, 0.8, 0.9)}
    report[h] = {"ROC-AUC": round(roc_auc_score(d["y"], d["score"]), 3), "PR-AUC": round(average_precision_score(d["y"], d["score"]), 3),
                 "precision": round(precision_score(d["y"], pred), 3), "recall": round(recall_score(d["y"], pred), 3),
                 "F1": round(f1_score(d["y"], pred), 3), "precision при recall": trade}
json.dump(report, open(f"{OUT}/gap_tabpfn.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(pd.DataFrame({h: {k: v for k, v in r.items() if k != "precision при recall"} for h, r in report.items()}).T.to_string())
print("компромисс на 30 днях (precision при recall 0.6/0.7/0.8/0.9):", report[30]["precision при recall"])
