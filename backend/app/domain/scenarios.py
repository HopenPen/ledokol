"""Сценарии «что если» (звёздочка 3). Сценарий — трансформация входов прогноза, без переобучения модели,
поэтому пересчёт мгновенный (FR-8.3), а базовый и негативный прогноз используют один и тот же seed —
разница на графике объясняется только сценарием.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from app.domain.calendar import working_days_after
from app.domain.types import Direction, EventSource, PlannedEvent

FIXED_COST_CATEGORIES = {"rent", "suppliers", "utilities", "it_accounting", "facility", "logistics"}


@dataclass(frozen=True, slots=True)
class ClientDelay:
    counterparty_key: str
    weeks: int  # 2–4 по кейсу


@dataclass(frozen=True, slots=True)
class ExtraExpense:
    day: date
    amount: float
    title: str = "Внеплановый расход"


@dataclass(frozen=True, slots=True)
class Scenario:
    client_delays: tuple[ClientDelay, ...] = ()
    revenue_drop_pct: float = 0.0          # 0..90
    extra_expenses: tuple[ExtraExpense, ...] = ()
    fixed_cost_increase_pct: float = 0.0   # 0..100
    extra_events: tuple[PlannedEvent, ...] = field(default=())

    @property
    def is_empty(self) -> bool:
        return not (self.client_delays or self.revenue_drop_pct or self.extra_expenses
                    or self.fixed_cost_increase_pct or self.extra_events)


def apply_to_events(sc: Scenario, events: list[PlannedEvent], as_of: date, horizon_end: date) -> list[PlannedEvent]:
    delays = {d.counterparty_key: d.weeks for d in sc.client_delays}
    out: list[PlannedEvent] = []
    for e in events:
        if e.direction is Direction.IN and e.counterparty_key in delays:
            new_day = working_days_after(e.event_date, delays[e.counterparty_key] * 5)[-1]
            if new_day <= horizon_end:
                out.append(replace(e, event_date=new_day, source=EventSource.SCENARIO,
                                   title=f"{e.title} (позже на {delays[e.counterparty_key]} нед.)"))
            continue  # ушло за горизонт — в прогнозе этих денег нет
        if sc.revenue_drop_pct and e.direction is Direction.IN:
            e = replace(e, amount=e.amount * (1 - sc.revenue_drop_pct / 100))
        if sc.fixed_cost_increase_pct and e.direction is Direction.OUT and e.category in FIXED_COST_CATEGORIES:
            e = replace(e, amount=e.amount * (1 + sc.fixed_cost_increase_pct / 100))
        out.append(e)
    for x in sc.extra_expenses:
        if as_of < x.day <= horizon_end:
            out.append(PlannedEvent(event_date=x.day, amount=x.amount, direction=Direction.OUT, title=x.title,
                                    category="other", source=EventSource.SCENARIO))
    out.extend(e for e in sc.extra_events if as_of < e.event_date <= horizon_end)
    return out
