"""Схемы API. Входные модели запрещают лишние поля (extra=forbid) — защита от mass assignment:
через PATCH нельзя подсунуть owner_id или data_version."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.types import ForecastResult, GapAlert, PlannedEvent


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --- auth -----------------------------------------------------------------------------------------------------
class LoginIn(_In):
    login: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


# --- companies ------------------------------------------------------------------------------------------------
class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    external_id: str
    name: str
    industry: str | None
    tax_regime: str
    min_balance: Decimal


class CompanyPatch(_In):
    name: str | None = Field(default=None, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    tax_regime: Literal["unknown", "usn", "osno", "eskhn"] | None = None
    min_balance: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)


class QualityOut(BaseModel):
    rows_total: int
    duplicates: int
    balance_jumps: int
    empty_purpose: int
    empty_inn: int
    history_working_days: int
    warnings: list[str]


class ImportOut(BaseModel):
    company: CompanyOut
    rows_total: int
    rows_new: int
    already_imported: bool
    quality: QualityOut


# --- operations -----------------------------------------------------------------------------------------------
class OperationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    op_date: date
    amount: Decimal
    direction: str
    counterparty_name: str
    purpose: str
    category: str
    category_label: str
    category_source: str
    quality: str


class CategoryPatch(_In):
    category: str = Field(max_length=32)
    apply_to_counterparty: bool = True


# --- events ---------------------------------------------------------------------------------------------------
class EventIn(_In):
    event_date: date
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    direction: Literal["in", "out"]
    kind: Literal["manual", "invoice_out", "invoice_in", "tax", "contract"] = "manual"
    title: str = Field(min_length=1, max_length=200)
    confidence: Literal["certain", "likely", "unsure"] = "likely"
    counterparty_key: str | None = Field(default=None, max_length=64)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_date: date
    amount: Decimal
    direction: str
    kind: str
    source: str
    title: str
    confidence: str
    status: str


# --- forecast -------------------------------------------------------------------------------------------------
class PointOut(BaseModel):
    date: date
    p10: float
    p50: float
    p90: float
    prob_below: float


class FutureEventOut(BaseModel):
    date: date
    amount: float
    direction: str
    title: str
    category: str
    source: str
    probability: float

    @classmethod
    def of(cls, e: PlannedEvent) -> FutureEventOut:
        return cls(date=e.event_date, amount=e.amount, direction=e.direction.value, title=e.title,
                   category=e.category, source=e.source.value, probability=e.probability)


class AlertOut(BaseModel):
    start: date
    end: date
    probability: float
    level: str
    shortfall: float
    worst_case: bool
    explanation: str
    causes: list[FutureEventOut]
    actions: list[str]

    @classmethod
    def of(cls, a: GapAlert) -> AlertOut:
        return cls(start=a.start, end=a.end, probability=a.probability, level=a.level, shortfall=a.shortfall,
                   worst_case=a.worst_case, explanation=a.explanation, causes=[FutureEventOut.of(c) for c in a.causes],
                   actions=a.actions)


class HistoryPoint(BaseModel):
    date: date
    balance: float


class ForecastOut(BaseModel):
    as_of: date
    last_balance: float
    threshold: float
    headline: str
    low_history: bool
    warnings: list[str]
    points: list[PointOut]
    events: list[FutureEventOut]
    alerts: list[AlertOut]

    @classmethod
    def of(cls, r: ForecastResult) -> ForecastOut:
        return cls(as_of=r.as_of, last_balance=r.last_balance, threshold=r.threshold, headline=r.headline,
                   low_history=r.low_history, warnings=r.data_warnings,
                   points=[PointOut(date=p.day, p10=p.p10, p50=p.p50, p90=p.p90, prob_below=p.prob_below)
                           for p in r.points],
                   events=[FutureEventOut.of(e) for e in r.events], alerts=[AlertOut.of(a) for a in r.alerts])


class ClientOut(BaseModel):
    counterparty_key: str
    name: str
    share: float


class DashboardOut(BaseModel):
    company: CompanyOut
    forecast: ForecastOut
    history: list[HistoryPoint]
    top_clients: list[ClientOut]
    model_version: str


# --- scenarios ------------------------------------------------------------------------------------------------
class ClientDelayIn(_In):
    counterparty_key: str = Field(max_length=64)
    weeks: int = Field(ge=1, le=8)


class ExtraExpenseIn(_In):
    date: date
    amount: Decimal = Field(gt=0, max_digits=16, decimal_places=2)
    title: str = Field(default="Внеплановый расход", max_length=200)


class ScenarioIn(_In):
    client_delays: list[ClientDelayIn] = Field(default_factory=list, max_length=5)
    revenue_drop_pct: float = Field(default=0, ge=0, le=90)
    extra_expenses: list[ExtraExpenseIn] = Field(default_factory=list, max_length=10)
    fixed_cost_increase_pct: float = Field(default=0, ge=0, le=100)


class ScenarioDelta(BaseModel):
    base_first_gap: date | None
    scenario_first_gap: date | None
    base_min_p50: float
    scenario_min_p50: float
    extra_shortfall: float


class ScenarioOut(BaseModel):
    base: ForecastOut
    scenario: ForecastOut
    delta: ScenarioDelta


# --- plan-fact, integrations, assistant -----------------------------------------------------------------------
class PlanFactRow(BaseModel):
    event_id: str | None
    title: str
    planned_date: date
    planned_amount: float
    status: str
    actual_amount: float
    actual_date: date | None


class SyncOut(BaseModel):
    created: int
    updated: int
    closed: int


class CounterpartyCheckOut(BaseModel):
    inn: str
    status: str
    has_tax_debt: bool
    risky: bool


class AskIn(_In):
    question: str = Field(min_length=2, max_length=500)


class AskOut(BaseModel):
    answer: str
    generated_by: str
