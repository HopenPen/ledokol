"""Будущие события (ручной ввод), сценарии «что если», план-факт, интеграции и ассистент."""
from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OwnedCompany
from app.api.schemas import (
    AskIn,
    AskOut,
    CounterpartyCheckOut,
    DailyPlanFactOut,
    DayCompareOut,
    EventIn,
    EventOut,
    EventPatch,
    ForecastOut,
    PlanFactRow,
    PreviewIn,
    RunOut,
    ScenarioDelta,
    ScenarioIn,
    ScenarioOut,
    SyncOut,
)
from app.core.config import get_settings
from app.db.models import PlannedEvent as PlannedEventRow
from app.domain.planfact import compare_daily, match_events
from app.domain.scenarios import ClientDelay, ExtraExpense, Scenario
from app.domain.types import ForecastResult
from app.integrations.http import IntegrationError
from app.llm.assistant import ask
from app.services.events import IdempotencyConflict, NewEvent, cancel_event, create_manual_event
from app.services.forecasting import company_model, run_forecast, run_preview, to_domain_event
from app.services.integrations import check_counterparties, sync_onec
from app.services.snapshots import runs_before

router = APIRouter(prefix="/companies/{company_id}", tags=["planning"])


def _model(session, company):
    try:
        return company_model(session, company)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для прогноза нужны платежи и известный остаток. Проверьте «Источники».") from None


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


@router.patch("/events/{event_id}", response_model=EventOut)
def patch_event(company: OwnedCompany, event_id: str, body: EventPatch, session: DbSession) -> PlannedEventRow:
    """Платёж не пришёл, но клиент обещал позже → переносим ожидание; или отменяем. Прогноз пересчитается сам."""
    ev = session.get(PlannedEventRow, event_id)
    if ev is None or ev.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    if body.event_date is not None:
        ev.event_date, ev.status = body.event_date, "expected"
    if body.status is not None:
        ev.status = body.status
    session.commit()
    return ev


# --- сценарии «что если» --------------------------------------------------------------------------------------
@router.post("/scenarios", response_model=ScenarioOut)
def run_scenario(company: OwnedCompany, body: ScenarioIn, session: DbSession) -> ScenarioOut:
    sc = _scenario(body)
    try:
        base, _ = run_forecast(session, company)
        neg, _ = run_forecast(session, company, scenario=sc)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для прогноза нужны платежи и известный остаток. Проверьте «Источники».") from None
    return ScenarioOut(base=ForecastOut.of(base), scenario=ForecastOut.of(neg), delta=_delta(base, neg))


def _scenario(body: ScenarioIn) -> Scenario:
    return Scenario(
        client_delays=tuple(ClientDelay(d.counterparty_key, d.weeks) for d in body.client_delays),
        revenue_drop_pct=body.revenue_drop_pct,
        extra_expenses=tuple(ExtraExpense(x.date, float(x.amount), x.title) for x in body.extra_expenses),
        fixed_cost_increase_pct=body.fixed_cost_increase_pct,
    )


@router.post("/forecast/preview", response_model=ForecastOut)
def preview(company: OwnedCompany, body: PreviewIn, session: DbSession) -> ForecastOut:
    """Черновик правок: исключить операции из обучения, добавить события, наложить сценарий. Ничего не сохраняет."""
    # Та же конвертация, что после сохранения: уверенность, тип и задержка оплаты не должны меняться.
    # Строки остаются вне сессии — предпросмотр не записывает события в БД.
    extra = [to_domain_event(PlannedEventRow(source="manual", **e.model_dump())) for e in body.extra_events]
    try:
        result = run_preview(session, company, exclude_db_ids=set(body.exclude_operation_ids),
                             extra_events=extra, scenario=_scenario(body), horizon=body.horizon)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для прогноза нужны платежи и известный остаток. Проверьте «Источники».") from None
    return ForecastOut.of(result)


def _delta(base: ForecastResult, neg: ForecastResult) -> ScenarioDelta:
    first = lambda r: r.alerts[0].start if r.alerts else None
    worst = lambda r: max((a.shortfall for a in r.alerts), default=0.0)
    return ScenarioDelta(base_first_gap=first(base), scenario_first_gap=first(neg),
                         base_min_p50=min(p.p50 for p in base.points), scenario_min_p50=min(p.p50 for p in neg.points),
                         extra_shortfall=max(0.0, worst(neg) - worst(base)))


# --- план-факт ------------------------------------------------------------------------------------------------
@router.get("/plan-fact", response_model=list[PlanFactRow])
def plan_fact(company: OwnedCompany, session: DbSession) -> list[PlanFactRow]:
    """Ожидаемые события, срок которых уже наступил по данным выписки: пришли / частично / не пришли."""
    cm = _model(session, company)
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


@router.get("/plan-fact/daily", response_model=DailyPlanFactOut)
def plan_fact_daily(company: OwnedCompany, session: DbSession, run_id: str | None = None) -> DailyPlanFactOut:
    """График план-факт (звёздочка 2): прогноз, сделанный по прошлой выписке, против фактического остатка."""
    cm = _model(session, company)
    runs = runs_before(session, company, cm.fitted.as_of)
    run = next((r for r in runs if r.id == run_id), None) if run_id else (runs[0] if runs else None)
    if run is None:
        return DailyPlanFactOut(run=None, rows=[], flagged_days=0)
    pts = [(p.day, float(p.p10), float(p.p50), float(p.p90)) for p in run.points]
    rows = compare_daily(pts, cm.prep.panel)
    return DailyPlanFactOut(run=RunOut.model_validate(run), flagged_days=sum(r.flagged for r in rows),
                            rows=[DayCompareOut(date=r.day, plan=r.plan, low=r.low, high=r.high, fact=r.fact,
                                                deviation=r.deviation, flagged=r.flagged) for r in rows])


# --- интеграции -----------------------------------------------------------------------------------------------
@router.post("/sync/1c", response_model=SyncOut)
def sync_1c(company: OwnedCompany, session: DbSession) -> SyncOut:
    as_of = _model(session, company).fitted.as_of
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
def assistant_ask(company: OwnedCompany, body: AskIn, session: DbSession, user: CurrentUser) -> AskOut:
    if get_settings().llm_mcp_enabled:
        try:
            from app.mcp_chat import ask as ask_mcp

            answer = asyncio.run(ask_mcp(body.question, scope=(user.login, company.external_id)))
            return AskOut(answer=answer, generated_by=f"{get_settings().llm_model}+mcp")
        except (ImportError, RuntimeError, ValueError, httpx.HTTPError, KeyError, IndexError):
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Ассистент сейчас недоступен. Попробуйте ещё раз.") from None
    try:
        result, _ = run_forecast(session, company)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для ответа нужны платежи и известный остаток. Проверьте «Источники».") from None
    a = ask(result, body.question)
    return AskOut(answer=a.text, generated_by=a.generated_by)

