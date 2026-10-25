"""Проверка реалистичности масштаба: компании кейса против реальной отчётности российских организаций (ФНС).

Источник: открытые данные ФНС «Сведения о суммах доходов и расходов по данным бухгалтерской отчётности»
(набор 7707329152-revexp, данные за 2025 год, лицензия открытая, совместима с CC-BY). Архив читаем потоком,
распаковывать на диск не нужно. Данные используем только для сравнения распределений, в обучение они не идут.

Что сравниваем:
1. годовой оборот (доход) — у кейса: операционные поступления за последние 12 месяцев выписки;
2. долю расходов в доходе — у кейса: операционные списания / операционные поступления за тот же период.
У ФНС берём только организации МСП по порогам выручки (до 2 млрд ₽, ст. 4 209-ФЗ) и с положительным доходом.

Запуск из analytics/: CASE_DIR=... uv run --project ../backend python experiments/fns_realism.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import zipfile

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath("../backend"))
sys.stdout.reconfigure(encoding="utf-8")

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.domain.categories import EXCLUDED_FROM_FORECAST  # noqa: E402
from app.domain.ingest import read_statement  # noqa: E402
from app.domain.pipeline import prepare_company, split_by_company  # noqa: E402

ZIP = "external/fns_revexp/data-20260925-structure-20180110.zip"
OUT = "experiments/out"
os.makedirs(OUT, exist_ok=True)
SME_MAX_REVENUE = 2_000_000_000
PAIR = re.compile(r'СумДоход="(-?[\d.]+)"\s+СумРасход="(-?[\d.]+)"')

# --- ФНС: поток по архиву (результат кешируем: разбор 2 121 файла занимает пару минут) ---
CACHE = f"{OUT}/fns_revexp.parquet"
rev, exp = [], []
with zipfile.ZipFile(ZIP) as z:
    names = [n for n in z.namelist() if n.endswith(".xml")] if not os.path.exists(CACHE) else []
    for i, n in enumerate(names):
        text = z.read(n).decode("utf-8", errors="replace")
        for a, b in PAIR.findall(text):
            rev.append(float(a))
            exp.append(float(b))
        if i % 500 == 499:
            print(f"ФНС: {i + 1}/{len(names)} файлов, организаций {len(rev):,}")
if os.path.exists(CACHE):
    fns = pd.read_parquet(CACHE)
else:
    fns = pd.DataFrame({"revenue": rev, "expenses": exp})
    fns.to_parquet(CACHE)
print(f"ФНС: всего организаций {len(fns):,}")
sme = fns[(fns["revenue"] > 0) & (fns["revenue"] <= SME_MAX_REVENUE)].copy()
sme["exp_ratio"] = (sme["expenses"] / sme["revenue"]).clip(0, 3)
print(f"ФНС: МСП с доходом > 0 и ≤ 2 млрд ₽: {len(sme):,} ({len(sme) / len(fns):.0%})")

# --- кейс: годовой оборот и доля расходов ---
raw = read_statement(open(os.path.join(os.environ["CASE_DIR"], "all_operations.csv"), "rb").read())
rows = []
for cid, df in split_by_company(raw).items():
    p = prepare_company(df)
    o = p.ops[p.ops["quality"].isin(["ok", "after_gap"]) & ~p.ops["category"].isin(EXCLUDED_FROM_FORECAST)]
    o = o[o["operation_date"] > o["operation_date"].max() - pd.Timedelta(days=365)]
    inflow, outflow = o.loc[o["direction"].eq("in"), "amount"].sum(), o.loc[o["direction"].eq("out"), "amount"].sum()
    if inflow > 0:
        rows.append({"company": cid, "revenue": inflow, "exp_ratio": min(outflow / inflow, 3.0)})
case = pd.DataFrame(rows)

q = [0.1, 0.25, 0.5, 0.75, 0.9]
summary = {
    "ФНС МСП, годовой доход, ₽": dict(zip(map(str, q), sme["revenue"].quantile(q).round(-3))),
    "Кейс, годовой доход, ₽": dict(zip(map(str, q), case["revenue"].quantile(q).round(-3))),
    "ФНС МСП, расходы/доход": dict(zip(map(str, q), sme["exp_ratio"].quantile(q).round(2))),
    "Кейс, расходы/доход": dict(zip(map(str, q), case["exp_ratio"].quantile(q).round(2))),
}
print(pd.DataFrame(summary).T.to_string())
json.dump({"fns_orgs": len(fns), "fns_sme": len(sme), "case_orgs": len(case), "quantiles": {k: {a: float(b) for a, b in v.items()} for k, v in summary.items()}},
          open(f"{OUT}/fns_realism.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# --- график: две гистограммы с общей шкалой, по плотности ---
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
C_FNS, C_CASE = "#1baf7a", "#2a78d6"
plt.rcParams.update({"figure.facecolor": SURF, "axes.facecolor": SURF, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlelocation": "left",
                     "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
                     "xtick.color": INK2, "ytick.color": INK2, "legend.frameon": False, "font.size": 10})
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
bins = np.logspace(5, 9.4, 45)
share = lambda x: np.full(len(x), 100 / len(x))  # noqa: E731  каждая организация — доля от группы, %
a1.hist(sme["revenue"], bins=bins, weights=share(sme), color=C_FNS, alpha=0.55, label=f"ФНС, МСП ({len(sme) / 1e6:.1f} млн орг.)")
a1.hist(case["revenue"], bins=bins, weights=share(case), color=C_CASE, alpha=0.65, label=f"кейс ({len(case)} компаний)")
a1.set_xscale("log")
a1.set(xlabel="годовой доход, ₽ (логарифмическая шкала)", ylabel="доля организаций в корзине, %")
a1.set_title("Годовой оборот")
a1.legend(loc="upper left")
b2 = np.linspace(0, 2, 41)
a2.hist(sme["exp_ratio"], bins=b2, weights=share(sme), color=C_FNS, alpha=0.55, label="ФНС, МСП")
a2.hist(case["exp_ratio"], bins=b2, weights=share(case), color=C_CASE, alpha=0.65, label="кейс")
a2.axvline(1, ls="--", lw=1, color=INK2)
a2.set(xlabel="расходы / доход (1 = выходим в ноль)", ylabel="доля организаций в корзине, %")
a2.set_title("Доля расходов в доходе")
a2.legend(loc="upper right")
plt.tight_layout()
plt.savefig(f"{OUT}/fns_realism.png", dpi=130)
print("график:", f"{OUT}/fns_realism.png")
