"""Показ работы обученной модели CatBoost на компаниях, которых она не видела.

1. Итоговая модель (RMSE + 9 квантилей) обучена на всех компаниях, КРОМЕ демо-компаний, и только на окнах, которые
   заканчиваются раньше даты прогноза. Модели лежат в catboost_out/v2/ (если их нет, скрипт обучит их заново).
2. Для каждой демо-компании делаем прогноз «в прошлое»: от даты за 30 рабочих дней до конца выписки, и сравниваем
   с тем, что было на самом деле.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend --extra ml --with matplotlib python catboost_demo.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from catboost import CatBoostRegressor, Pool  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from scipy.stats import norm  # noqa: E402

from app.domain.categories import EXCLUDED_FROM_FORECAST  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.ml_flow import NON_FEATURES, make_cum_rows, operational_flow  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

H, MIN_HIST, TRAIN_STEP = 30, 60, 3
TRAIN_H = [1, 2, 3, 5, 7, 10, 14, 20, 25, 30]
QS = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95]
DEMO = ["C009", "C066", "C082", "C117"]          # демо-компании из сценария защиты
ALERT_THR = 0.15                                  # порог тревоги CatBoost: его выбирала кросс-валидация на других компаниях
SEED = 7
OUT = "catboost_out/v2"
FIG = "experiments/out"
os.makedirs(OUT, exist_ok=True)
os.makedirs(FIG, exist_ok=True)
CATS = ["industry", "target_dow", "source"]

root = os.environ["CASE_DIR"]
raw = read_statement(open(os.path.join(root, "all_operations.csv"), "rb").read())
companies = pd.read_csv(os.path.join(root, "companies.csv"), sep=";", encoding="utf-8-sig", dtype=str)
INDUSTRY = dict(zip(companies["company_id"], companies["industry"]))
preps = {cid: prepare_company(df) for cid, df in sorted(split_by_company(raw).items())}
flows = {c: operational_flow(p) for c, p in preps.items()}
gaps = {c: p.panel["after_gap"].to_numpy() for c, p in preps.items()}

cutoff_pos = {c: len(flows[c]) - 1 - H for c in DEMO}
CUTOFF_DATE = min(flows[c].index[cutoff_pos[c]] for c in DEMO)
print("демо-компании:", DEMO, "дата прогноза:", CUTOFF_DATE.date())


def X(df, force_case=False):
    x = df.drop(columns=[c for c in NON_FEATURES if c in df.columns])
    return x.assign(source="case") if force_case else x


if os.path.exists(f"{OUT}/mean.cbm") and os.path.exists(f"{OUT}/quantile.cbm") and not os.environ.get("RETRAIN"):
    m_mean = CatBoostRegressor().load_model(f"{OUT}/mean.cbm")
    m_q = CatBoostRegressor().load_model(f"{OUT}/quantile.cbm")
    print("модели загружены из", OUT)
else:
    train_ids = [c for c in preps if c not in DEMO]
    rng = np.random.default_rng(SEED)
    val_ids = set(rng.choice(train_ids, size=int(len(train_ids) * 0.15), replace=False))
    frames = [make_cum_rows(flows[c], INDUSTRY.get(c, "unknown"), step=TRAIN_STEP, min_history=MIN_HIST, after_gap=gaps[c],
                            company=c, horizons=TRAIN_H, max_target_date=CUTOFF_DATE) for c in train_ids]
    allr = pd.concat([f for f in frames if len(f)], ignore_index=True)
    tr, va = allr[~allr["company"].isin(val_ids)], allr[allr["company"].isin(val_ids)]
    lo, hi = tr["y"].quantile([0.005, 0.995])
    tr, va = tr.assign(y=tr["y"].clip(lo, hi)), va.assign(y=va["y"].clip(lo, hi))

    def fit_cb(loss):
        m = CatBoostRegressor(loss_function=loss, eval_metric=loss, iterations=1500, learning_rate=0.06, depth=6,
                              l2_leaf_reg=5.0, random_seed=SEED, od_type="Iter", od_wait=100, use_best_model=True,
                              verbose=False, thread_count=-1)
        m.fit(Pool(X(tr), tr["y"], cat_features=CATS), eval_set=Pool(X(va, True), va["y"], cat_features=CATS))
        return m

    m_mean = fit_cb("RMSE")
    m_q = fit_cb("MultiQuantile:alpha=" + ",".join(map(str, QS)))
    m_mean.save_model(f"{OUT}/mean.cbm")
    m_q.save_model(f"{OUT}/quantile.cbm")
    json.dump({"quantiles": QS, "horizon": H, "train_horizons": TRAIN_H, "clip": [float(lo), float(hi)],
               "trained_on_companies": sorted(tr["company"].unique().tolist()), "held_out_demo": DEMO,
               "forecast_date_limit": str(CUTOFF_DATE.date()), "trees_mean": m_mean.tree_count_,
               "trees_quantile": m_q.tree_count_}, open(f"{OUT}/meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("модели обучены и сохранены в", OUT)


def prob_below(q: np.ndarray, thr: float = 0.0) -> np.ndarray:
    """P(остаток < thr) по дням из квантилей; за краями — нормальный хвост."""
    out = []
    for row in q:
        if row[0] <= thr <= row[-1]:
            out.append(np.interp(thr, row, QS))
        else:
            sigma = max((row[-1] - row[0]) / (2 * norm.ppf(QS[-1])), 1e-9)
            p = norm.cdf((thr - row[QS.index(0.5)]) / sigma)
            out.append(min(p, QS[0]) if thr < row[0] else max(p, QS[-1]))
    return np.array(out)


INK, INK2, GRID, BLUE, RED, GREEN = "#0b0b0b", "#52514e", "#e6e5e0", "#2a78d6", "#d03b3b", "#1a9a6c"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "axes.titlecolor": INK,
                     "axes.spines.top": False, "axes.spines.right": False, "figure.facecolor": "white",
                     "axes.facecolor": "white", "axes.grid": True, "grid.color": GRID})
SHORT = lambda s: (s or "").replace("Сельское хозяйство", "С/х").replace("Розница: ", "")  # noqa: E731

fig, axes = plt.subplots(2, 2, figsize=(13.5, 9.2))
summary = []
for ax, c in zip(axes.ravel(), DEMO):
    prep, pos = preps[c], cutoff_pos[c]
    panel, ops = prep.panel.reset_index(drop=True), prep.ops
    excl = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["quality"].ne("duplicate")].groupby("operation_date")["signed"].sum()
    bal = panel["balance"].to_numpy()
    inj = np.cumsum(panel["date"].map(excl).fillna(0.0).to_numpy())
    fact = (bal - (inj - inj[pos]))[pos + 1: pos + 1 + H]                  # остаток без денег владельца после даты прогноза
    rows = make_cum_rows(flows[c], INDUSTRY.get(c, "unknown"), step=TRAIN_STEP, min_history=MIN_HIST, after_gap=gaps[c],
                         company=c, positions=[pos])
    rows = rows[rows["h"].le(H)].sort_values("h")
    sc, b0 = rows["scale"].iloc[0], bal[pos]
    p50 = b0 + sc * m_mean.predict(X(rows, True))
    q = b0 + sc * np.sort(m_q.predict(X(rows, True)), axis=1)
    risk = float(prob_below(q).max())
    alert, gap = risk >= ALERT_THR, bool((fact < 0).any())
    ongoing = b0 < 0
    verdict, vcolor = (("верно: разрыв найден", GREEN) if alert and gap else
                       ("верно: тревоги нет, разрыва нет", GREEN) if not alert and not gap else
                       ("пропущен разрыв", RED) if gap else ("ложная тревога", RED))
    M = 1e6
    d = np.arange(1, H + 1)
    ax.axhspan(min(bal[pos - 40: pos + 1].min(), fact.min(), q[:, 1].min(), 0) / M * 1.15, 0, color=RED, alpha=0.07, lw=0)
    ax.plot(np.arange(-40, 1), bal[pos - 40: pos + 1] / M, color=INK2, lw=1.8)
    ax.fill_between(d, q[:, 1] / M, q[:, -2] / M, color=BLUE, alpha=0.17, lw=0)
    ax.plot(d, p50 / M, color=BLUE, lw=2.4)
    ax.plot(d, fact / M, color=INK, lw=2.4)
    ax.axhline(0, color=RED, lw=1.2, ls="--")
    ax.axvline(0, color=INK2, lw=1, ls=":")
    first_neg = np.flatnonzero(fact < 0)
    if gap and not ongoing and len(first_neg):
        ax.plot([d[first_neg[0]]], [fact[first_neg[0]] / M], "o", ms=10, color=RED, mec="white", mew=2, zorder=5)
        ax.text(0.02, 0.96, f"● остаток ушёл ниже нуля на {first_neg[0] + 1}-й день", transform=ax.transAxes, fontsize=10.5,
                color=RED, va="top", fontweight="bold")
    ax.set_xlabel("рабочих дней от даты прогноза")
    ax.set_ylabel("остаток на счёте, млн ₽")
    note = "\nна дату прогноза остаток уже ниже нуля" if ongoing else ""
    ax.set_title(f"{c} · {SHORT(INDUSTRY.get(c))}", loc="left", fontsize=13, fontweight="bold", pad=42)
    ax.text(0, 1.115, f"Риск разрыва по модели {risk:.0%}, порог тревоги {ALERT_THR:.0%}", transform=ax.transAxes, fontsize=11, color=INK)
    ax.text(0, 1.035, verdict + (" (разрыв уже идёт на дату прогноза)" if ongoing else ""), transform=ax.transAxes,
            fontsize=11.5, color=vcolor, fontweight="bold")
    err = np.abs(p50 - fact) / sc
    summary.append({"company": c, "industry": INDUSTRY.get(c), "forecast_from": str(panel["date"].iloc[pos].date()),
                    "risk_max_pct": round(100 * risk), "alert": bool(alert), "gap_actual": gap, "already_negative": bool(ongoing),
                    "verdict": verdict, "mae_h10": round(float(err[9]), 2), "mae_h30": round(float(err[-1]), 2),
                    "inside_corridor_pct": round(100 * float(((fact >= q[:, 1]) & (fact <= q[:, -2])).mean()))})
handles = [Line2D([0], [0], color=INK2, lw=1.8, label="история остатка"),
           Line2D([0], [0], color=BLUE, lw=2.4, label="прогноз CatBoost"),
           Patch(color=BLUE, alpha=0.25, label="коридор (80% вариантов)"),
           Line2D([0], [0], color=INK, lw=2.4, label="что было на самом деле (без денег владельца)"),
           Line2D([0], [0], color=RED, lw=1.2, ls="--", label="ноль: ниже этой линии не хватает денег")]
fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=11, bbox_to_anchor=(0.5, -0.005))
plt.tight_layout(rect=(0, 0.05, 1, 1), h_pad=3.2)
plt.savefig(f"{FIG}/catboost_demo.png", dpi=130, bbox_inches="tight")
print(pd.DataFrame(summary)[["company", "risk_max_pct", "alert", "gap_actual", "already_negative", "verdict", "mae_h30", "inside_corridor_pct"]].to_string(index=False))
json.dump(summary, open(f"{FIG}/catboost_demo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
