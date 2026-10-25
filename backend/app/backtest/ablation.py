"""Аблация источников: насколько каждый источник будущих событий улучшает прогноз (критерий жюри №3).

Берём одни и те же окна бэктеста и считаем гибрид в нескольких вариантах — с источником и без него. Отключённый
источник не исчезает, а уходит в статистический слой «размазанным» средним (см. fit(drop=...)): сравнение
«поштучно против средним» честное. Реестр счетов восстанавливается из назначений платежей (domain/invoices.py).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.domain.calendar import working_days_after
from app.domain.forecast import fit, forecast
from app.domain.invoices import build_registry, open_invoice_events

# имя варианта → (какие источники отключить, режим счетов: None / add / aware)
VARIANTS: dict[str, tuple[frozenset, str | None]] = {
    "базовый (без счетов)": (frozenset(), None),
    "+ счета поверх среднего": (frozenset(), "add"),
    "+ счета вместо среднего": (frozenset(), "aware"),
    "− налоговый календарь": (frozenset({"taxes"}), None),
    "− регулярные платежи": (frozenset({"recurring"}), None),
    "− налоги и регулярные платежи": (frozenset({"taxes", "recurring"}), None),
}


def run_ablation(preps: dict, windows: list[dict], horizon: int = 30, n_sims: int = 200, seed: int = 7) -> dict[str, list[dict]]:
    """По каждому окну и варианту — траектории P10/P50/P90 и вероятность ниже нуля по дням."""
    registries = {cid: build_registry(p.ops) for cid, p in preps.items()}
    out: dict[str, list[dict]] = {name: [] for name in VARIANTS}
    for w in windows:
        prep, cutoff = preps[w["company"]], w["cutoff"]
        panel = prep.panel.reset_index(drop=True)
        hist_ops, hist_panel = prep.ops[prep.ops["operation_date"].le(cutoff)], panel.iloc[: w["pos"] + 1]
        fits: dict[tuple, object] = {}
        for name, (drop, inv) in VARIANTS.items():
            key = (drop, inv == "aware")
            if key not in fits:
                fits[key] = fit(hist_ops, hist_panel, drop=drop, invoice_aware=inv == "aware")
            m = fits[key]
            events = open_invoice_events(registries[w["company"]], cutoff, working_days_after(m.as_of, horizon)[-1]) if inv else []
            res = forecast(m, events, horizon=horizon, n_sims=n_sims, seed=seed)
            out[name].append({
                "p10": np.array([p.p10 for p in res.points]), "p50": np.array([p.p50 for p in res.points]),
                "p90": np.array([p.p90 for p in res.points]), "prob": np.array([p.prob_below for p in res.points]),
                "n_events": len(events)})
    return out


def score_table(per_variant: dict[str, list[dict]]) -> pd.DataFrame:
    """Оценка риска окна = максимум по дням вероятности «остаток ниже нуля» (как в ноутбуке)."""
    return pd.DataFrame({name: [r["prob"].max() for r in rows] for name, rows in per_variant.items()})
