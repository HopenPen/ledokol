"""Ручной факт с защитой от повторной отправки; отдельно от ожидаемых событий."""
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.db.models import Company, ManualPaymentRequest, Operation
from app.services.balances import check_payment_date, lock_company, set_point
from app.services.events import IdempotencyConflict
from app.services.history import refresh_history


@dataclass(frozen=True)
class NewPayment:
    op_date: date
    amount: Decimal
    direction: str
    counterparty_name: str
    purpose: str
    balance_eod: Decimal | None = None  # Совместимость со старым API; новая форма это поле не отправляет.
    counterparty_inn: str = ""


def create_payment(session: Session, company: Company, payment: NewPayment, key: str | None) -> tuple[Operation, bool]:
    body = asdict(payment)
    for name in ("amount", "balance_eod"):
        if body[name] is not None:
            body[name] = str(body[name].normalize())
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    def previous():
        receipt = session.get(ManualPaymentRequest, (company.id, key)) if key else None
        if receipt and receipt.request_hash != fingerprint:
            raise IdempotencyConflict
        return session.get(Operation, receipt.operation_id) if receipt else None

    lock_company(session, company)
    if found := previous():
        return found, False
    try:
        check_payment_date(session, company, payment.op_date)
        operation = Operation(company_id=company.id, source_operation_id="manual:" + uuid7(), **asdict(payment))
        operation.counterparty_inn = payment.counterparty_inn or None
        session.add(operation)
        session.flush()
        if payment.balance_eod is not None:
            set_point(session, company, payment.op_date, payment.balance_eod, "legacy")
        if key:
            session.add(ManualPaymentRequest(company_id=company.id, key=key, request_hash=fingerprint, operation_id=operation.id))
        refresh_history(session, company)
        session.execute(update(Company).where(Company.id == company.id).values(data_version=Company.data_version + 1))
        session.commit()
        return operation, True
    except IntegrityError:
        session.rollback()
        if found := previous():
            return found, False
        raise
