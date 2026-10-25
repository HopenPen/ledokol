from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Direction(StrEnum):
    IN = "in"
    OUT = "out"


class EventSource(StrEnum):
    """Откуда взялось будущее событие — показывается пользователю рядом с каждой суммой (US-4)."""

    HISTORY = "history"        # регулярный платёж, найденный в выписке
    CALENDAR = "calendar"      # налоговый календарь
    MANUAL = "manual"          # ручной ввод предпринимателя
    ONEC = "1c"                # счета/договоры из 1С
    SCENARIO = "scenario"      # «что если»


class Confidence(StrEnum):
    CERTAIN = "certain"
    LIKELY = "likely"
    UNSURE = "unsure"


CONFIDENCE_PROB = {Confidence.CERTAIN: 1.0, Confidence.LIKELY: 0.8, Confidence.UNSURE: 0.5}


@dataclass(frozen=True, slots=True)
class PlannedEvent:
    """Ожидаемое поступление/списание на конкретную дату."""

    event_date: date
    amount: float
    direction: Direction
    title: str
    category: str
    source: EventSource
    probability: float = 1.0          # вероятность, что событие вообще случится
    date_jitter_days: int = 0         # насколько может сдвинуться дата (рабочих дней)
    counterparty_key: str | None = None
    ref: str | None = None            # id события в БД / номер счёта

    @property
    def signed(self) -> float:
        return self.amount if self.direction is Direction.IN else -self.amount


@dataclass(frozen=True, slots=True)
class ForecastPoint:
    day: date
    p10: float
    p50: float
    p90: float
    prob_below: float  # доля траекторий ниже порога в этот день
    p25: float | None = None   # «обычный» коридор P25–P75; P10–P90 остаётся для плана-факта и риска
    p75: float | None = None


@dataclass(slots=True)
class GapAlert:
    start: date
    end: date
    probability: float
    shortfall: float          # сколько не хватит в медианном (или плохом) сценарии, ₽
    worst_case: bool          # True — разрыв только в плохом сценарии (P10)
    level: str                # «почти наверняка» / «вероятно» / «возможно»
    causes: list[PlannedEvent] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    explanation: str = ""


@dataclass(slots=True)
class ForecastResult:
    as_of: date
    last_balance: float
    threshold: float
    points: list[ForecastPoint]
    events: list[PlannedEvent]
    alerts: list[GapAlert]
    headline: str
    data_warnings: list[str] = field(default_factory=list)
    low_history: bool = False
