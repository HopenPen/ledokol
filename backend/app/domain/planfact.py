"""План-факт (звёздочка 2): какие ожидаемые события пришли, пришли частично или не пришли."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.domain.types import PlannedEvent

DATE_TOL_DAYS = 5
AMOUNT_TOL = 0.2


@dataclass(frozen=True, slots=True)
class Match:
    event: PlannedEvent
    status: str                 # received | partial | missed | pending
    actual_amount: float
    actual_date: date | None


def match_events(events: list[PlannedEvent], ops: pd.DataFrame, as_of: date) -> list[Match]:
    """Сопоставляет события с фактом. Одна операция закрывает не больше одного события."""
    used: set[int] = set()
    out: list[Match] = []
    for e in sorted(events, key=lambda x: x.event_date):
        lo, hi = pd.Timestamp(e.event_date - timedelta(days=DATE_TOL_DAYS)), pd.Timestamp(e.event_date + timedelta(days=DATE_TOL_DAYS))
        cand = ops[ops["direction"].eq(e.direction.value) & ops["operation_date"].between(lo, hi)
                   & ~ops.index.isin(list(used))]
        if e.counterparty_key:
            cand = cand[cand["cp_key"].eq(e.counterparty_key)]
        else:
            cand = cand[(cand["amount"] - e.amount).abs() <= AMOUNT_TOL * e.amount]
        if not cand.empty:
            hit = cand.iloc[(cand["amount"] - e.amount).abs().argsort()[:1]]
            used.update(hit.index)
            amt = float(hit["amount"].iloc[0])
            status = "received" if amt >= (1 - AMOUNT_TOL) * e.amount else "partial"
            out.append(Match(e, status, amt, hit["operation_date"].iloc[0].date()))
        elif e.event_date + timedelta(days=DATE_TOL_DAYS) < as_of:
            out.append(Match(e, "missed", 0.0, None))
        else:
            out.append(Match(e, "pending", 0.0, None))
    return out


@dataclass(frozen=True, slots=True)
class DayCompare:
    day: date
    plan: float          # P50 сохранённого прогноза
    low: float           # P10
    high: float          # P90
    fact: float          # фактический остаток на конец дня
    deviation: float     # факт − план
    flagged: bool        # факт вышел за «обычный разброс» — подсвечиваем на графике


def compare_daily(points: list[tuple[date, float, float, float]], panel: pd.DataFrame) -> list[DayCompare]:
    """План (снимок прогноза) против факта по дням — для графика из звёздочки 2.

    Сравниваем только дни, по которым уже есть выписка. «Отклонение выделено», если факт вне P10–P90:
    это и есть «случилось то, чего модель не ждала», а не произвольный порог в процентах.
    """
    fact = panel.set_index(panel["date"].dt.date)["balance"]
    out = []
    for day, p10, p50, p90 in points:
        if day not in fact.index:
            continue
        f = float(fact[day])
        out.append(DayCompare(day, p50, p10, p90, f, f - p50, not (p10 <= f <= p90)))
    return out


def weekly_plan_fact(matches: list[Match]) -> pd.DataFrame:
    rows = [{"week": pd.Timestamp(m.event.event_date).to_period("W").start_time.date(),
             "plan": m.event.signed, "fact": m.actual_amount * (1 if m.event.signed > 0 else -1)}
            for m in matches if m.status != "pending"]
    if not rows:
        return pd.DataFrame(columns=["week", "plan", "fact", "deviation_pct"])
    df = pd.DataFrame(rows).groupby("week", as_index=False)[["plan", "fact"]].sum()
    df["deviation_pct"] = ((df["fact"] - df["plan"]) / df["plan"].abs().where(df["plan"] != 0)).fillna(0) * 100
    return df
