"""Регулярные платежи и поступления: «скелет» прогноза (слой A).

Серия = компания × контрагент × категория × направление. Регулярна, если ≥ 3 платежей и интервал стабилен
(коэффициент вариации ≤ 0,35). В EDA так нашлись почти все аренды, связь, ПО, коммуналка, кредиты и лизинг.
"""
from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.domain.calendar import next_working_day
from app.domain.categories import EXCLUDED_FROM_FORECAST, RETAIL, label
from app.domain.types import Direction, EventSource, PlannedEvent

_PERIODS = [  # (код, мин. интервал, макс. интервал, шаг в днях | None = календарный месяц)
    ("weekly", 5, 9, 7),
    ("biweekly", 12, 17, 14),
    ("monthly", 26, 35, None),
    ("quarterly", 80, 100, None),
]
_SKIP = RETAIL | EXCLUDED_FROM_FORECAST | {"tax"}   # налоги — отдельный календарь, розница — слой B


@dataclass(frozen=True, slots=True)
class RecurringSeries:
    cp_key: str
    counterparty_name: str
    category: str
    direction: Direction
    period: str
    step_days: int | None
    typical_day: int
    expected_amount: float
    amount_cv: float
    last_date: date
    n_payments: int
    member_index: tuple[int, ...]


def detect_recurring(ops: pd.DataFrame, as_of: date, lookback_days: int = 365, max_cv: float = 0.35,
                     ) -> list[RecurringSeries]:
    since = pd.Timestamp(as_of - timedelta(days=lookback_days))
    cand = ops[ops["quality"].eq("ok") & ~ops["category"].isin(_SKIP) & ops["operation_date"].ge(since)
               & ops["operation_date"].le(pd.Timestamp(as_of))]
    out: list[RecurringSeries] = []
    for (direction, cp_key, category), g in cand.groupby(["direction", "cp_key", "category"], sort=False):
        series = _as_series(g, direction, cp_key, category, as_of, max_cv)
        if series is None and g["operation_date"].nunique() >= 6:
            # Зарплата «аванс + окончательный расчёт» — это две месячные серии в одной: делим по половине месяца.
            first_half = g["operation_date"].dt.day <= 15
            halves = [_as_series(part, direction, cp_key, category, as_of, max_cv, monthly_only=True)
                      for part in (g[first_half], g[~first_half])]
            out += [s for s in halves if s is not None]
        elif series is not None:
            out.append(series)
    return out


def _as_series(g: pd.DataFrame, direction: str, cp_key: str, category: str, as_of: date, max_cv: float,
               monthly_only: bool = False) -> RecurringSeries | None:
    """Одна серия платежей → RecurringSeries, если интервалы стабильны и серия ещё жива; иначе None."""
    per_day = g.groupby("operation_date")["amount"].sum()
    if len(per_day) < 3:
        return None
    gaps = np.diff(per_day.index.values).astype("timedelta64[D]").astype(int)
    med = float(np.median(gaps))
    periods = [p for p in _PERIODS if p[0] == "monthly"] if monthly_only else _PERIODS
    period = next(((code, step) for code, lo, hi, step in periods if lo <= med <= hi), None)
    if period is None or np.std(gaps) / med > max_cv:
        return None
    last = per_day.index[-1].date()
    if (as_of - last).days > 1.6 * med:      # серия прекратилась (ушёл клиент, закрыли договор)
        return None
    amounts = per_day.to_numpy()
    return RecurringSeries(
        cp_key=str(cp_key), counterparty_name=str(g["counterparty_name"].iloc[-1]), category=category,
        direction=Direction(direction), period=period[0], step_days=period[1],
        typical_day=int(np.median(per_day.index.day)),
        expected_amount=float(np.median(amounts[-3:])),
        amount_cv=float(np.std(amounts) / np.mean(amounts)) if amounts.mean() else 0.0,
        last_date=last, n_payments=len(per_day), member_index=tuple(g.index.tolist()),
    )


def _add_months(d: date, months: int, day: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(day, _cal.monthrange(y, m)[1]))


def project_series(s: RecurringSeries, as_of: date, end: date) -> list[PlannedEvent]:
    dates: list[date] = []
    if s.step_days:
        cur = s.last_date + timedelta(days=s.step_days)
        while cur <= end:
            if cur > as_of:
                dates.append(next_working_day(cur))
            cur += timedelta(days=s.step_days)
    else:
        step = 1 if s.period == "monthly" else 3
        k = 1
        while (cur := _add_months(s.last_date, step * k, s.typical_day)) <= end:
            if cur > as_of:
                dates.append(next_working_day(cur))
            k += 1
    jitter = {"weekly": 1, "biweekly": 1, "monthly": 2, "quarterly": 3}[s.period]
    prob = 0.95 if s.direction is Direction.OUT else 0.85
    return [PlannedEvent(
        event_date=d, amount=s.expected_amount, direction=s.direction,
        title=f"{label(s.category)}: {s.counterparty_name}", category=s.category, source=EventSource.HISTORY,
        probability=prob, date_jitter_days=jitter, counterparty_key=s.cp_key,
    ) for d in dates if d <= end]
