"""Операции с категориями и ручная правка категории (FR-2.3)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, OwnedCompany
from app.api.schemas import CategoryPatch, OperationOut
from app.db.models import Company, Operation
from app.domain.categories import CATEGORIES, label

router = APIRouter(tags=["operations"])


def _out(op: Operation) -> OperationOut:
    return OperationOut(id=op.id, op_date=op.op_date, amount=op.amount, direction=op.direction,
                        counterparty_name=op.counterparty_name, purpose=op.purpose, category=op.category,
                        category_label=label(op.category), category_source=op.category_source, quality=op.quality)


@router.get("/companies/{company_id}/operations", response_model=list[OperationOut])
def list_operations(company: OwnedCompany, session: DbSession, limit: int = Query(100, ge=1, le=500),
                    offset: int = Query(0, ge=0), category: str | None = None) -> list[OperationOut]:
    q = select(Operation).where(Operation.company_id == company.id)
    if category:
        q = q.where(Operation.category == category)
    rows = session.scalars(q.order_by(Operation.op_date.desc(), Operation.source_operation_id.desc())
                           .limit(limit).offset(offset))
    return [_out(r) for r in rows]


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
