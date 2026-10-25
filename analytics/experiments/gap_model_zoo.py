"""Сравнение моделей для поиска разрывов на тех же окнах и фолдах, что у CatBoost (gap_classifier_v2): только чтение выборки."""
import json, sys, time, warnings
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_recall_curve, precision_score, recall_score, roc_auc_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
O = Path(__file__).parent / "out"
DS = pd.read_csv(O / "gap_v2_dataset.csv")
inds = sorted(DS["industry"].dropna().unique())
DS["industry_code"] = DS["industry"].map({n: i for i, n in enumerate(inds)})
META = ["company", "t", "industry", "end_date", "y", "is_eval", "fold"]
FE = [c for c in DS.columns if c not in META]
print("признаков:", len(FE), "| строк:", len(DS))

def models():
    from catboost import CatBoostClassifier
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    yield "CatBoost", lambda: CatBoostClassifier(iterations=600, learning_rate=0.05, depth=6, l2_leaf_reg=6, random_seed=7, verbose=False, thread_count=8)
    yield "LightGBM", lambda: LGBMClassifier(n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5, random_state=7, verbose=-1, n_jobs=8)
    yield "XGBoost", lambda: XGBClassifier(n_estimators=500, learning_rate=0.03, max_depth=5, subsample=0.8, colsample_bytree=0.8, reg_lambda=5, random_state=7, n_jobs=8, eval_metric="logloss")
    yield "HistGradientBoosting", lambda: HistGradientBoostingClassifier(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=5, random_state=7)
    yield "ExtraTrees", lambda: make_pipeline(SimpleImputer(strategy="median"), ExtraTreesClassifier(n_estimators=500, min_samples_leaf=5, n_jobs=8, random_state=7))
    yield "Логистическая регрессия", lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=1000))
    yield "MLP (нейросеть)", lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), MLPClassifier(hidden_layer_sizes=(64, 32), alpha=1e-3, early_stopping=True, max_iter=300, random_state=7))

def best_f1(y, s):
    p, r, t = precision_recall_curve(y, s); f = 2 * p * r / (p + r + 1e-12); return t[f[:-1].argmax()]
def p_at_r(y, s, r0):
    p, r, _ = precision_recall_curve(y, s); return float(p[r >= r0].max())

rows, SC = [], {}
for name, make in models():
    t0 = time.time(); sc = []
    for f in sorted(DS["fold"].unique()):
        tr = DS[(DS.is_eval == 0) & (DS.fold != f)]; te = DS[(DS.is_eval == 1) & (DS.fold == f)]
        m = make(); m.fit(tr[FE], tr["y"])
        sc.append(te[["company", "t", "h", "y"]].assign(score=m.predict_proba(te[FE])[:, 1]))
    S = pd.concat(sc); SC[name] = S
    for h in (30, "все"):
        d = S if h == "все" else S[S.h == h]
        y, s = d.y.to_numpy(), d.score.to_numpy(); th = best_f1(y, s); pr = (s >= th).astype(int)
        rows.append({"модель": name, "горизонт": h, "ROC-AUC": roc_auc_score(y, s), "PR-AUC": average_precision_score(y, s), "precision": precision_score(y, pr),
                     "recall": recall_score(y, pr), "F1": f1_score(y, pr), "precision при recall 0,8": p_at_r(y, s, 0.8), "секунд": time.time() - t0})
    print(f"{name}: готово за {time.time()-t0:.0f} с", flush=True)
R = pd.DataFrame(rows)
R.to_csv(O / "gap_model_zoo.csv", index=False)
pd.concat([v.assign(model=k) for k, v in SC.items()]).to_parquet(O / "gap_model_zoo_scores.parquet")
pd.set_option("display.width", 200)
print(R[R["горизонт"] == 30].drop(columns="горизонт").round(3).to_string(index=False))
