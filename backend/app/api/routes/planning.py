"""Будущие события (ручной ввод), сценарии «что если», план-факт, интеграции и ассистент."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import DbSession, OwnedCompany
from app.api.schemas import (
    AskIn, AskOut, CounterpartyCheckOut, EventIn, EventOut, ForecastOut, PlanFactRow, ScenarioDelta, ScenarioIn,
    ScenarioOut, SyncOut,
)
from app.db.models import PlannedEvent as PlannedEventRow
from app.domain.planfact import match_events
from app.domain.scenarios import ClientDelay, ExtraExpense, Scenario
from app.domain.types import ForecastResult
from app.integrations.http import IntegrationError
from app.llm.assistant import ask
from app.services.events import IdempotencyConflict, NewEvent, cancel_event, create_manual_event
from app.services.forecasting import company_model, run_forecast, to_domain_event
from app.services.integrations import check_counterparties, sync_onec

router = APIRouter(prefix="/companies/{company_id}", tags=["planning"])


# --- ручные события -------------------------------------------------------------------------------------------
@router.get("/events", response_model=list[EventOut])
def list_events(company: OwnedCompany, session: DbSession) -> list[PlannedEventRow]:
    return list(session.scalars(select(PlannedEventRow).where(PlannedEventRow.company_id == company.id)
                                .order_by(PlannedEventRow.event_date)))


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def add_event(company: OwnedCompany, body: EventIn, session: DbSession, response: Response,
              idempotency_key: str | None = Header(default=None, max_length=64)) -> PlannedEventRow:
    """«Клиент обещал 300 000 ₽ 20-го» → событие сразу участвует в прогнозе. Повтор с тем же ключом безопасен."""
    try:
        ev, created = create_manual_event(session, company, NewEvent(**body.model_dump()), idempotency_key)
    except IdempotencyConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот Idempotency-Key уже использован с другими данными") from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return ev


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(company: OwnedCompany, event_id: str, session: DbSession) -> None:
    # Компания уже проверена на владение; событие ищем только внутри неё — чужое не найдётся (404).
    ev = session.get(PlannedEventRow, event_id)
    if ev is None or ev.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    cancel_event(session, ev)


# --- сценарии «что если» --------------------------------------------------------------------------------------
@router.post("/scenarios", response_model=ScenarioOut)
def run_scenario(company: OwnedCompany, body: ScenarioIn, session: DbSession) -> ScenarioOut:
    sc = Scenario(
        client_delays=tuple(ClientDelay(d.counterparty_key, d.weeks) for d in body.client_delays),
        revenue_drop_pct=body.revenue_drop_pct,
        extra_expenses=tuple(ExtraExpense(x.date, float(x.amount), x.title) for x in body.extra_expenses),
        fixed_cost_increase_pct=body.fixed_cost_increase_pct,
    )
    try:
        base, _ = run_forecast(session, company)
        neg, _ = run_forecast(session, company, scenario=sc)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала загрузите выписку") from None
    return ScenarioOut(base=ForecastOut.of(base), scenario=ForecastOut.of(neg), delta=_delta(base, neg))


def _delta(base: ForecastResult, neg: ForecastResult) -> ScenarioDelta:
    first = lambda r: r.alerts[0].start if r.alerts else None  # noqa: E731
    worst = lambda r: max((a.shortfall for a in r.alerts), default=0.0)  # noqa: E731
    return ScenarioDelta(base_first_gap=first(base), scenario_first_gap=first(neg),
                         base_min_p50=min(p.p50 for p in base.points), scenario_min_p50=min(p.p50 for p in neg.points),
                         extra_shortfall=max(0.0, worst(neg) - worst(base)))


# --- план-факт ------------------------------------------------------------------------------------------------
@router.get("/plan-fact", response_model=list[PlanFactRow])
def plan_fact(company: OwnedCompany, session: DbSession) -> list[PlanFactRow]:
    """Ожидаемые события, срок которых уже наступил по данным выписки: пришли / частично / не пришли."""
    cm = company_model(session, company)
    rows = list(session.scalars(select(PlannedEventRow).where(
        PlannedEventRow.company_id == company.id, PlannedEventRow.status.in_(["expected", "received", "partial", "missed"]),
        PlannedEventRow.event_date <= cm.fitted.as_of)))
    matches = match_events([to_domain_event(r) for r in rows], cm.prep.ops, cm.fitted.as_of)
    by_ref = {r.id: r for r in rows}
    for m in matches:                      # фиксируем статус, чтобы событие ушло из прогноза
        row = by_ref.get(m.event.ref)
        if row is not None and m.status != "pending":
            row.status = m.status
    session.commit()
    return [PlanFactRow(event_id=m.event.ref, title=m.event.title, planned_date=m.event.event_date,
                        planned_amount=m.event.amount, status=m.status, actual_amount=m.actual_amount,
                        actual_date=m.actual_date) for m in matches]


# --- интеграции -----------------------------------------------------------------------------------------------
@router.post("/sync/1c", response_model=SyncOut)
def sync_1c(company: OwnedCompany, session: DbSession) -> SyncOut:
    as_of = company_model(session, company).fitted.as_of
    try:
        r = sync_onec(session, company, as_of)
    except IntegrationError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "1С сейчас недоступна, прогноз построен по выписке") from None
    return SyncOut(created=r.created, updated=r.updated, closed=r.closed)


@router.post("/sync/fns", response_model=list[CounterpartyCheckOut])
def sync_fns(company: OwnedCompany, session: DbSession) -> list[CounterpartyCheckOut]:
    try:
        statuses = check_counterparties(session, company)
    except IntegrationError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Сервис ФНС сейчас недоступен") from None
    return [CounterpartyCheckOut(inn=s.inn, status=s.status, has_tax_debt=s.has_tax_debt, risky=s.risky)
            for s in statuses]


# --- ассистент ------------------------------------------------------------------------------------------------
@router.post("/assistant/ask", response_model=AskOut)
def assistant_ask(company: OwnedCompany, body: AskIn, session: DbSession) -> AskOut:
    result, _ = run_forecast(session, company)
    a = ask(result, body.question)
    return AskOut(answer=a.text, generated_by=a.generated_by)

