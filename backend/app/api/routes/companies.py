"""Компании, загрузка выписки и главный экран (дашборд) одним запросом."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.api.deps import CurrentUser, DbSession, OwnedCompany
from app.api.schemas import (
    AlertOut,
    BalanceOut,
    ClientOut,
    CompanyCreate,
    CompanyOut,
    CompanyPatch,
    DashboardOut,
    EventOut,
    ForecastOut,
    HistoryPoint,
    ImportOut,
    InitialBalanceIn,
    QualityOut,
)
from app.core.config import get_settings
from app.core.ids import uuid7
from app.db.models import Company
from app.db.models import PlannedEvent as PlannedEventRow
from app.domain.balances import BalanceError
from app.domain.forecast import MODEL_VERSION
from app.domain.ingest import StatementFormatError
from app.services.balances import balance_status, set_initial_balance
from app.services.companies import delete_company
from app.services.forecasting import run_forecast
from app.services.statements import import_statement

router = APIRouter(prefix="/companies", tags=["companies"])
_HISTORY_DAYS = 90


async def _read_upload(file: UploadFile) -> bytes:
    limit = get_settings().max_upload_mb * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше допустимого размера")
    return raw


def _import_out(results) -> list[ImportOut]:
    return [ImportOut(company=CompanyOut.model_validate(r.company), rows_total=r.rows_total, rows_new=r.rows_new,
                      rows_matched=r.rows_matched,
                      already_imported=r.already_imported,
                      quality=QualityOut(**{k: getattr(r.quality, k) for k in QualityOut.model_fields}))
            for r in results]


@router.get("", response_model=list[CompanyOut])
def list_companies(session: DbSession, user: CurrentUser) -> list[Company]:
    return list(session.scalars(select(Company).where(Company.owner_id == user.id).order_by(Company.external_id)))


@router.post("", response_model=CompanyOut, status_code=status.HTTP_201_CREATED)
def create_company(body: CompanyCreate, session: DbSession, user: CurrentUser) -> Company:
    company = Company(owner_id=user.id, external_id="manual:" + uuid7().replace("-", "")[:24], name=body.name)
    session.add(company)
    session.commit()
    return company


@router.post("/import", response_model=list[ImportOut], status_code=status.HTTP_201_CREATED)
async def import_new(file: UploadFile, session: DbSession, user: CurrentUser) -> list[ImportOut]:
    """Загрузил выписку → компания создана → прогноз готов. Ноль настройки (TOE: снимаем барьер сложности)."""
    try:
        raw = await _read_upload(file)
        return _import_out(await run_in_threadpool(import_statement, session, user, raw, filename=file.filename or "statement.csv"))
    except (StatementFormatError, BalanceError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.post("/{company_id}/statements", response_model=list[ImportOut])
async def upload_statement(company: OwnedCompany, file: UploadFile, session: DbSession, user: CurrentUser) -> list[ImportOut]:
    """Дозагрузка выписки (например, за прошедшую неделю) — новые операции добавятся, старые не задвоятся."""
    try:
        raw = await _read_upload(file)
        return _import_out(await run_in_threadpool(import_statement, session, user, raw, company, file.filename or "statement.csv"))
    except (StatementFormatError, BalanceError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company: OwnedCompany) -> Company:
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_company(company: OwnedCompany, session: DbSession) -> Response:
    delete_company(session, company)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{company_id}", response_model=CompanyOut)
def patch_company(company: OwnedCompany, body: CompanyPatch, session: DbSession) -> Company:
    for field, value in body.model_dump(exclude_unset=True).items():   # только поля из allowlist схемы
        setattr(company, field, value)
    session.commit()
    return company


@router.get("/{company_id}/balance", response_model=BalanceOut)
def get_balance(company: OwnedCompany, session: DbSession) -> dict:
    return balance_status(session, company)


@router.put("/{company_id}/balance/initial", response_model=BalanceOut)
def put_initial_balance(company: OwnedCompany, body: InitialBalanceIn, session: DbSession) -> dict:
    try:
        return set_initial_balance(session, company, body.date, body.amount)
    except BalanceError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.get("/{company_id}/dashboard", response_model=DashboardOut)
def dashboard(company: OwnedCompany, session: DbSession) -> DashboardOut:
    try:
        result, cm = run_forecast(session, company)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для прогноза нужны платежи и известный остаток: загрузите выписку или укажите начальный остаток в «Источниках»") from None
    hist = cm.prep.panel.tail(_HISTORY_DAYS)
    return DashboardOut(
        company=CompanyOut.model_validate(company), forecast=ForecastOut.of(result),
        history=[HistoryPoint(date=d.date(), balance=float(b)) for d, b in zip(hist["date"], hist["balance"])],
        top_clients=[ClientOut(counterparty_key=k, name=n, share=s) for k, n, s in cm.fitted.top_clients],
        model_version=MODEL_VERSION,
        missed_payments=[EventOut.model_validate(e) for e in session.scalars(select(PlannedEventRow).where(
            PlannedEventRow.company_id == company.id, PlannedEventRow.status == "missed")
            .order_by(PlannedEventRow.event_date.desc()).limit(10))],
    )


@router.get("/{company_id}/forecast", response_model=ForecastOut)
def get_forecast(company: OwnedCompany, session: DbSession, horizon: int = 30) -> ForecastOut:
    horizon = max(5, min(horizon, 90))
    try:
        result, _ = run_forecast(session, company, horizon=horizon)
    except LookupError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Для прогноза нужны платежи и известный остаток: загрузите выписку или укажите начальный остаток в «Источниках»") from None
    return ForecastOut.of(result)


@router.get("/{company_id}/alerts", response_model=list[AlertOut])
def get_alerts(company: OwnedCompany, session: DbSession) -> list[AlertOut]:
    try:
        result, _ = run_forecast(session, company)
    except LookupError:
        return []
    return [AlertOut.of(a) for a in result.alerts]
