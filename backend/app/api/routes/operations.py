"""Операции с категориями и ручная правка категории (FR-2.3)."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Response, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession, OwnedCompany
from app.api.schemas import CategoryPatch, OperationOut, OperationSearchIn, PaymentIn
from app.db.models import Company, Operation
from app.domain.balances import BalanceError
from app.domain.categories import CATEGORIES, label
from app.services.events import IdempotencyConflict
from app.services.payments import NewPayment, create_payment

router = APIRouter(tags=["operations"])


def _out(op: Operation) -> OperationOut:
    return OperationOut(id=op.id, op_date=op.op_date, amount=op.amount, direction=op.direction,
                        counterparty_name=op.counterparty_name, purpose=op.purpose, category=op.category,
                        category_label=label(op.category), category_source=op.category_source, quality=op.quality,
                        counterparty_inn=op.counterparty_inn, balance_eod=op.balance_eod,
                        source="manual" if op.source_operation_id.startswith("manual:") else "statement")


@router.post("/companies/{company_id}/operations", response_model=OperationOut, status_code=status.HTTP_201_CREATED)
def add_payment(company: OwnedCompany, body: PaymentIn, session: DbSession, response: Response,
                idempotency_key: str | None = Header(default=None, min_length=1, max_length=64)) -> OperationOut:
    try:
        operation, created = create_payment(session, company, NewPayment(**body.model_dump()), idempotency_key)
    except IdempotencyConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "Этот ключ уже использован с другими данными платежа") from None
    except BalanceError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    if not created:
        response.status_code = status.HTTP_200_OK
    return _out(operation)


@router.get("/companies/{company_id}/operations", response_model=list[OperationOut])
def list_operations(company: OwnedCompany, session: DbSession, limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0), category: str | None = None) -> list[OperationOut]:
    q = select(Operation).where(Operation.company_id == company.id)
    if category:
        q = q.where(Operation.category == category)
    rows = session.scalars(q.order_by(Operation.op_date.desc(), Operation.source_operation_id.desc())
                           .limit(limit).offset(offset))
    return [_out(r) for r in rows]


@router.post("/companies/{company_id}/operations/search", response_model=list[OperationOut])
def search_operations(company: OwnedCompany, body: OperationSearchIn, session: DbSession) -> list[OperationOut]:
    """Поиск до пагинации. Строка в теле запроса, чтобы имена не попадали в access log как часть URL."""
    query = select(Operation).where(Operation.company_id == company.id)
    if body.category:
        query = query.where(Operation.category == body.category)
    if body.query:
        matching_categories = [code for code in CATEGORIES if body.query.lower() in label(code).lower()]
        query = query.where(or_(Operation.counterparty_name.icontains(body.query, autoescape=True),
                                Operation.purpose.icontains(body.query, autoescape=True),
                                Operation.category.in_(matching_categories)))
    rows = session.scalars(query.order_by(Operation.op_date.desc(), Operation.source_operation_id.desc())
                           .offset(body.offset).limit(body.limit))
    return [_out(row) for row in rows]


@router.patch("/operations/{operation_id}/category", response_model=list[OperationOut])
def patch_category(operation_id: str, body: CategoryPatch, session: DbSession, user: CurrentUser) -> list[OperationOut]:
    if body.category not in CATEGORIES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Неизвестная категория")
    op = session.scalar(select(Operation).join(Company).where(Operation.id == operation_id, Company.owner_id == user.id))
    if op is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Операция не найдена")
    targets = [op]
    if body.apply_to_counterparty:
        # Правка распространяется на все операции этого контрагента в том же направлении с той же старой категорией.
        targets = list(session.scalars(select(Operation).where(
            Operation.company_id == op.company_id, Operation.direction == op.direction,
            Operation.counterparty_name == op.counterparty_name, Operation.category == op.category)))
    for t in targets:
        t.category, t.category_source, t.confidence = body.category, "user", 1.0
    op.company.data_version += 1   # категории влияют на модель → переобучим при следующем прогнозе
    session.commit()
    return [_out(t) for t in targets]
