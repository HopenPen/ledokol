"""Эксперимент: помогают ли реальные продажи сети 1С прогнозу розничной выручки (слой B).

Слой B — эквайринг, СБП, наличные и маркетплейсы. Единственное место, где внешние данные подходят по смыслу:
в продажах 1С есть только выручка, без расходов, поэтому подмешивать их к чистому потоку нельзя (это проверено
в catboost_merged.ipynb), а к выручке — можно.

Цель — накопленная выручка за h рабочих дней в долях обычного дневного оборота компании (как в основной модели).
Сравниваем на одних и тех же компаниях и окнах:
  Б0  простое «средний дневной уровень за 60 дней × h» — то, что делает гибрид;
  Б1  CatBoost, обучен только на кейсе;
  Б2  CatBoost, кейс + продажи 1С (фильтр похожести по компаниям, вес кейса ≥ 50%, внешних строк не больше двух объёмов кейса).
Проверка: 5 фолдов по компаниям; обучающие окна заканчиваются до первого проверочного; доверительные интервалы
бутстрепом по компаниям.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml --with matplotlib python experiments/retail_1c.py
"""
from __future__ import annotations

import glob
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

from app.domain.calendar import is_working_day, next_working_day  # noqa: E402
from app.domain.categories import RETAIL  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import NON_FEATURES, adversarial_filter, make_cum_rows, mix_weights  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

H, STEP_EVAL, N_EVAL, MIN_HIST, TRAIN_STEP, EXT_STEP = 30, 5, 12, 60, 3, 7
TRAIN_H = [1, 2, 3, 5, 7, 10, 14, 20, 25, 30]
EVAL_H = [5, 10, 20, 30]
SEED = 7
OUT = "experiments/out"
os.makedirs(OUT, exist_ok=True)
CATS = ["industry", "target_dow", "source"]

# --- кейс: розничный поток по компаниям ---
root = os.environ["CASE_DIR"]
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
flows, gaps = {}, {}
for cid, df in split_by_company(raw).items():
    p = prepare_company(df)
    good = p.ops[p.ops["quality"].isin(["ok", "after_gap"])]
    days = pd.DatetimeIndex(p.panel["date"])
    b = good[good["category"].isin(RETAIL)].groupby("operation_date")["signed"].sum().reindex(days, fill_value=0.0)
    inflow = good.loc[good["direction"].eq("in"), "amount"].sum()
    if inflow and b.clip(lower=0).sum() / inflow >= 0.05:        # как в основной модели: розница ≥ 5% поступлений
        flows[cid], gaps[cid] = b, p.panel["after_gap"].to_numpy()
ids = np.array(sorted(flows))
print(f"компаний с розницей: {len(ids)} из {raw['company_id'].nunique()}")

# --- продажи 1С ---
sales = pd.read_csv(glob.glob("external/1c/sales_train.csv")[0])
sales["date"] = pd.to_datetime(sales["date"], format="%d.%m.%Y")
sales["revenue"] = sales["item_price"].clip(lower=0) * sales["item_cnt_day"]
sales["date"] = sales["date"].map(lambda d: pd.Timestamp(next_working_day(d.date())))   # выходные → ближайший рабочий
onec = {}
for shop, g in sales.groupby("shop_id"):
    daily = g.groupby("date")["revenue"].sum()
    wd = pd.DatetimeIndex([d for d in pd.date_range(daily.index.min(), daily.index.max()) if is_working_day(d.date())])
    s = daily.reindex(wd, fill_value=0.0)
    if len(s) > 250 and (s > 0).mean() > 0.8:                     # только «живые» магазины без долгих закрытий
        onec[f"1c_{shop}"] = s
print(f"магазинов 1С: {len(onec)} из {sales['shop_id'].nunique()}; {sales['date'].min().date()}…{sales['date'].max().date()}")

# --- проверочные окна ---
eval_pos = {}
for cid in ids:
    n = len(flows[cid])
    eval_pos[cid] = [pos for k in range(N_EVAL) if (pos := n - 1 - H - k * STEP_EVAL) >= MIN_HIST
                     and not gaps[cid][pos + 1: pos + 1 + H].any()]
EVAL_START = min(flows[c].index[p] for c in ids for p in eval_pos[c])
print(f"проверочных окон: {sum(len(v) for v in eval_pos.values())}; первое: {EVAL_START.date()}")

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


ext_all = pd.concat([make_cum_rows(s, "Розница (1С)", step=EXT_STEP, min_history=MIN_HIST, source="1c_retail", company=k,
                                   horizons=TRAIN_H) for k, s in onec.items()], ignore_index=True)
print(f"строк 1С до фильтра: {len(ext_all):,}")


def X(df, force_case=False):
    x = df.drop(columns=[c for c in NON_FEATURES if c in df.columns])
    return x.assign(source="case") if force_case else x


def fit_cb(tr, va):
    m = CatBoostRegressor(loss_function="RMSE", iterations=1500, learning_rate=0.06, depth=6, l2_leaf_reg=5.0,
                          random_seed=SEED, od_type="Iter", od_wait=100, use_best_model=True, verbose=False, thread_count=-1)
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
    ext = adversarial_filter(tr, ext_all, max_p_external=0.8)
    cap = int(2 * len(tr))
    if len(ext) > cap:                                             # лимит объёма по компаниям: окна не рвём
        order = ext["company"].drop_duplicates().sample(frac=1.0, random_state=SEED)
        per = ext.groupby("company").size().reindex(order)
        ext = ext[ext["company"].isin(per.index[per.cumsum() <= cap])]
    tr_ext = pd.concat([tr, ext.assign(y=ext["y"].clip(lo, hi))], ignore_index=True)
    m1, m2 = fit_cb(tr, va), fit_cb(tr_ext, va)
    te = rows_case([c for c in ids if fold_of[c] == f], positions=True)
    te = te[te["h"].isin(EVAL_H)]
    te = te.assign(b0=te["mean60_x_h"], b1=m1.predict(X(te, True)), b2=m2.predict(X(te, True)))
    recs.append(te[["company", "cutoff", "h", "y", "b0", "b1", "b2"]])
    log.append({"фолд": f, "кейс строк": len(tr), "1С магазинов после фильтра": ext["company"].nunique(),
                "1С строк": len(ext), "деревьев Б1": m1.tree_count_, "деревьев Б2": m2.tree_count_,
                "секунд": round(time.time() - t0)})
    print(log[-1])
R = pd.concat(recs, ignore_index=True)

# --- метрики и доверительные интервалы (бутстреп по компаниям) ---
def boot(df, col, h, fn, n=500):
    g = [d for _, d in df[df["h"].eq(h)].groupby("company")]
    r, vals = np.random.default_rng(0), []
    for _ in range(n):
        s = pd.concat([g[i] for i in r.integers(0, len(g), len(g))])
        vals.append(fn(s, col))
    return np.percentile(vals, [2.5, 97.5])


rmse = lambda d, c: float(np.sqrt(np.mean((d[c] - d["y"]) ** 2)))  # noqa: E731
mae = lambda d, c: float(np.mean(np.abs(d[c] - d["y"])))  # noqa: E731
names = {"b0": "Б0 уровень×h", "b1": "Б1 CatBoost, кейс", "b2": "Б2 CatBoost, кейс + 1С"}
table = {}
for h in EVAL_H:
    d = R[R["h"].eq(h)]
    for c, nme in names.items():
        lo_, hi_ = boot(R, c, h, rmse)
        table[(nme, h)] = {"RMSE": rmse(d, c), "ДИ": f"{lo_:.2f}–{hi_:.2f}", "MAE": mae(d, c)}
T = pd.DataFrame(table).T
print(T.round(3).to_string())
# парное сравнение Б2 против Б1: доля компаний, где 1С помогла (бутстрепный ДИ разности RMSE)
diff = {}
for h in EVAL_H:
    d = R[R["h"].eq(h)]
    per_co = d.groupby("company").apply(lambda x: pd.Series({"b1": rmse(x, "b1"), "b2": rmse(x, "b2")}))
    delta = lambda s, c: rmse(s, "b2") - rmse(s, "b1")  # noqa: E731
    lo_, hi_ = boot(R, "b2", h, delta)
    diff[h] = {"RMSE(Б2) − RMSE(Б1)": rmse(d, "b2") - rmse(d, "b1"), "ДИ": f"{lo_:.3f}…{hi_:.3f}",
               "компаний, где 1С помогла, %": round(100 * float((per_co["b2"] < per_co["b1"]).mean()))}
print(pd.DataFrame(diff).T.to_string())
json.dump({"table": {f"{a}|{b}": v for (a, b), v in table.items()}, "paired": diff, "folds": log},
          open(f"{OUT}/retail_1c.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)

# --- график: RMSE по горизонтам ---
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
COL = {"Б0 уровень×h": "#eda100", "Б1 CatBoost, кейс": "#2a78d6", "Б2 CatBoost, кейс + 1С": "#1baf7a"}
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "xtick.color": INK2, "ytick.color": INK2, "legend.frameon": False, "font.size": 10})
fig, ax = plt.subplots(figsize=(7.5, 4.2))
for nme, color in COL.items():
    ax.plot(EVAL_H, [table[(nme, h)]["RMSE"] for h in EVAL_H], "-o", ms=7, lw=2, color=color, label=nme,
            markeredgecolor=SURF, markeredgewidth=2)
ax.set(xlabel="горизонт, рабочих дней", ylabel="RMSE накопленной выручки (дневных оборотов)", xticks=EVAL_H)
ax.set_title("Розничная выручка: помогают ли продажи 1С")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig(f"{OUT}/retail_1c.png", dpi=130)
