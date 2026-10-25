"""Розничная выручка: CatBoost против розничного слоя самого гибрида (слой B), на одних и тех же окнах.

В retail_1c.py сравнивали с простым «средний уровень × h» — это слабее, чем у гибрида: он ещё учитывает день недели
(робастное среднее выручки по каждому дню недели за последние дни). Здесь сравниваем честно:
  Г   слой B гибрида: сумма ожидаемой выручки по дням недели на h рабочих дней вперёд (функция fit из приложения);
  К   CatBoost, 1 500 деревьев (как в прошлом эксперименте);
  К+  CatBoost, до 4 000 деревьев (в прошлый раз ранняя остановка не сработала — проверяем недообучение);
  А   среднее Г и К+ (простой ансамбль для слоя B).
Цель — накопленная выручка за h рабочих дней в дневных оборотах компании. 88 компаний с розницей, 5 фолдов по
компаниям, обучающие окна заканчиваются до первого проверочного, доверительные интервалы — бутстреп по компаниям.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml --with matplotlib python experiments/retail_vs_hybrid.py
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from catboost import CatBoostRegressor, Pool  # noqa: E402
from sklearn.model_selection import StratifiedGroupKFold  # noqa: E402

from app.domain.calendar import working_days_after  # noqa: E402
from app.domain.categories import RETAIL  # noqa: E402
from app.domain.forecast import fit  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import NON_FEATURES, make_cum_rows, mix_weights  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

H, STEP_EVAL, N_EVAL, MIN_HIST, TRAIN_STEP = 30, 5, 12, 60, 3
TRAIN_H = [1, 2, 3, 5, 7, 10, 14, 20, 25, 30]
EVAL_H = [5, 10, 20, 30]
SEED = 7
OUT = "experiments/out"
os.makedirs(OUT, exist_ok=True)
CATS = ["industry", "target_dow", "source"]

root = os.environ["CASE_DIR"]
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
flows, gaps, preps = {}, {}, {}
for cid, df in split_by_company(raw).items():
    p = prepare_company(df)
    good = p.ops[p.ops["quality"].isin(["ok", "after_gap"])]
    days = pd.DatetimeIndex(p.panel["date"])
    b = good[good["category"].isin(RETAIL)].groupby("operation_date")["signed"].sum().reindex(days, fill_value=0.0)
    inflow = good.loc[good["direction"].eq("in"), "amount"].sum()
    if inflow and b.clip(lower=0).sum() / inflow >= 0.05:
        flows[cid], gaps[cid], preps[cid] = b, p.panel["after_gap"].to_numpy(), p
ids = np.array(sorted(flows))
print(f"компаний с розницей: {len(ids)}")

eval_pos = {}
for cid in ids:
    n = len(flows[cid])
    eval_pos[cid] = [pos for k in range(N_EVAL) if (pos := n - 1 - H - k * STEP_EVAL) >= MIN_HIST
                     and not gaps[cid][pos + 1: pos + 1 + H].any()]
EVAL_START = min(flows[c].index[p] for c in ids for p in eval_pos[c])

fold_of = {}
sgkf = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=SEED)
for f, (_, te) in enumerate(sgkf.split(ids, [INDUSTRY.get(c, "unknown") for c in ids], groups=ids)):
    fold_of.update({c: f for c in ids[te]})


def rows_case(cids, positions=False) -> pd.DataFrame:
    frames = []
    for c in cids:
        kw = {"positions": eval_pos[c]} if positions else {"horizons": TRAIN_H, "max_target_date": EVAL_START}
        r = make_cum_rows(flows[c], INDUSTRY.get(c, "unknown"), step=TRAIN_STEP, min_history=MIN_HIST,
                          after_gap=gaps[c], company=c, **kw)
        if len(r):
            frames.append(r)
    return pd.concat(frames, ignore_index=True)


def hybrid_layer_b(rows: pd.DataFrame) -> np.ndarray:
    """Накопленная выручка слоя B гибрида на h дней вперёд в долях масштаба строки (тот же масштаб, что цель)."""
    out = np.zeros(len(rows))
    cache: dict[tuple, np.ndarray] = {}
    for i, (c, cutoff, h, sc) in enumerate(zip(rows["company"], rows["cutoff"], rows["h"], rows["scale"])):
        key = (c, cutoff)
        if key not in cache:
            prep = preps[c]
            panel = prep.panel[prep.panel["date"].le(cutoff)]
            m = fit(prep.ops[prep.ops["operation_date"].le(cutoff)], panel)
            dows = np.array([d.weekday() for d in working_days_after(cutoff.date(), H)])
            cache[key] = np.cumsum(m.revenue_dow[dows])
        out[i] = cache[key][h - 1] / sc
    return out


def X(df, force_case=False):
    x = df.drop(columns=[c for c in NON_FEATURES if c in df.columns])
    return x.assign(source="case") if force_case else x


def fit_cb(tr, va, iters):
    m = CatBoostRegressor(loss_function="RMSE", iterations=iters, learning_rate=0.06, depth=6, l2_leaf_reg=5.0,
                          random_seed=SEED, od_type="Iter", od_wait=150, use_best_model=True, verbose=False, thread_count=-1)
    m.fit(Pool(X(tr), tr["y"], cat_features=CATS, weight=mix_weights(tr)),
          eval_set=Pool(X(va, True), va["y"], cat_features=CATS))
    return m


recs, log = [], []
rng = np.random.default_rng(SEED)
for f in range(5):
    t0 = time.time()
    train_ids = [c for c in ids if fold_of[c] != f]
    val_ids = set(rng.choice(train_ids, size=max(2, int(len(train_ids) * 0.15)), replace=False))
    allr = rows_case(train_ids)
    tr, va = allr[~allr["company"].isin(val_ids)], allr[allr["company"].isin(val_ids)]
    lo, hi = tr["y"].quantile([0.005, 0.995])
    tr, va = tr.assign(y=tr["y"].clip(lo, hi)), va.assign(y=va["y"].clip(lo, hi))
    m1, m2 = fit_cb(tr, va, 1500), fit_cb(tr, va, 4000)
    te = rows_case([c for c in ids if fold_of[c] == f], positions=True)
    te = te[te["h"].isin(EVAL_H)]
    te = te.assign(g=hybrid_layer_b(te), k=m1.predict(X(te, True)), kp=m2.predict(X(te, True)))
    te["a"] = (te["g"] + te["kp"]) / 2
    recs.append(te[["company", "cutoff", "h", "y", "g", "k", "kp", "a"]])
    log.append({"фолд": f, "деревьев К": m1.tree_count_, "деревьев К+": m2.tree_count_, "секунд": round(time.time() - t0)})
    print(log[-1])
R = pd.concat(recs, ignore_index=True)

rmse = lambda d, c: float(np.sqrt(np.mean((d[c] - d["y"]) ** 2)))  # noqa: E731
names = {"g": "Г слой B гибрида", "k": "К CatBoost 1500", "kp": "К+ CatBoost до 4000", "a": "А среднее Г и К+"}


def boot(col_fn, h, n=500):
    g = [d for _, d in R[R["h"].eq(h)].groupby("company")]
    r, vals = np.random.default_rng(0), []
    for _ in range(n):
        s = pd.concat([g[i] for i in r.integers(0, len(g), len(g))])
        vals.append(col_fn(s))
    return np.percentile(vals, [2.5, 97.5])


table = {}
for h in EVAL_H:
    d = R[R["h"].eq(h)]
    for c, nme in names.items():
        lo_, hi_ = boot(lambda s, c=c: rmse(s, c), h)
        table[(nme, h)] = {"RMSE": rmse(d, c), "ДИ": f"{lo_:.2f}–{hi_:.2f}"}
T = pd.DataFrame(table).T
print(T.round(3).to_string())
paired = {}
for h in EVAL_H:
    d = R[R["h"].eq(h)]
    row = {}
    for c in ("k", "kp", "a"):
        lo_, hi_ = boot(lambda s, c=c: rmse(s, c) - rmse(s, "g"), h)
        row[f"{names[c]} − Г"] = f"{rmse(d, c) - rmse(d, 'g'):+.2f} [{lo_:+.2f}; {hi_:+.2f}]"
    paired[h] = row
print(pd.DataFrame(paired).T.to_string())
json.dump({"table": {f"{a}|{b}": v for (a, b), v in table.items()}, "paired": paired, "folds": log},
          open(f"{OUT}/retail_vs_hybrid.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)

INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
COL = {"Г слой B гибрида": "#eb6834", "К CatBoost 1500": "#7aa7dd", "К+ CatBoost до 4000": "#2a78d6", "А среднее Г и К+": "#e87ba4"}
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "xtick.color": INK2, "ytick.color": INK2, "legend.frameon": False, "font.size": 10})
fig, ax = plt.subplots(figsize=(7.5, 4.2))
for nme, color in COL.items():
    ax.plot(EVAL_H, [table[(nme, h)]["RMSE"] for h in EVAL_H], "-o", ms=7, lw=2, color=color, label=nme,
            markeredgecolor=SURF, markeredgewidth=2)
ax.set(xlabel="горизонт, рабочих дней", ylabel="RMSE накопленной выручки (дневных оборотов)", xticks=EVAL_H)
ax.set_title("Розничная выручка: CatBoost против слоя B гибрида")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig(f"{OUT}/retail_vs_hybrid.png", dpi=130)
