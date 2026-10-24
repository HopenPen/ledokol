"""Хранение опорных остатков и обновление их дневной проекции в операциях."""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import BalancePoint, Company, Operation
from app.domain.balances import BalanceError, Point, daily_balances


def lock_company(session: Session, company: Company) -> None:
    # Сериализует факт, выписку и смену начального остатка в PostgreSQL.
    session.execute(select(Company.id).where(Company.id == company.id).with_for_update())


def set_point(session: Session, company: Company, day: date, amount: Decimal, kind: str) -> None:
    point = session.get(BalancePoint, (company.id, day, kind))
    if point is None:
        session.add(BalancePoint(company_id=company.id, day=day, amount=amount, kind=kind))
    else:
        point.amount = amount


def initial_point(session: Session, company: Company) -> BalancePoint | None:
    return session.scalar(select(BalancePoint).where(BalancePoint.company_id == company.id, BalancePoint.kind == "initial"))


def check_payment_date(session: Session, company: Company, day: date) -> None:
    initial = initial_point(session, company)
    earlier_anchor = session.scalar(select(BalancePoint.day).where(
        BalancePoint.company_id == company.id, BalancePoint.kind != "initial", BalancePoint.day <= day).limit(1))
    if initial and day < initial.day and earlier_anchor is None:
        raise BalanceError("Дата платежа раньше начального остатка. Сначала перенесите дату начального остатка в «Источниках».")


def recalculate_balances(session: Session, company: Company) -> None:
    session.flush()
    points = list(session.scalars(select(BalancePoint).where(BalancePoint.company_id == company.id)))
    operations = list(session.scalars(select(Operation).where(Operation.company_id == company.id)))
    net = defaultdict(Decimal)
    for op in operations:
        net.setdefault(op.op_date, Decimal(0))
        if op.quality != "duplicate":
            net[op.op_date] += op.amount if op.direction == "in" else -op.amount
    balances = daily_balances(net, [Point(p.day, p.amount, p.kind) for p in points])
    for op in operations:
        op.balance_eod = balances[op.op_date]
    session.flush()


def balance_status(session: Session, company: Company) -> dict:
    points = list(session.scalars(select(BalancePoint).where(BalancePoint.company_id == company.id)))
    operations = list(session.scalars(select(Operation).where(Operation.company_id == company.id)
                                    .order_by(Operation.op_date, Operation.source_operation_id)))
    latest = next((op for op in reversed(operations) if op.balance_eod is not None), None)
    initial = next((p for p in points if p.kind == "initial"), None)
    # На одной дате выписка надёжнее ранее вручную введённого закрывающего остатка.
    effective = [p for p in points if p.kind != "initial" or not any(
        other.kind != "initial" and other.day <= p.day for other in points)]
    anchor = max(effective, key=lambda p: (p.day, {"initial": 0, "legacy": 1, "statement": 2}[p.kind]), default=None)
    as_of = max(filter(None, [latest.op_date if latest else None, anchor.day if anchor else None]), default=None)
    amount = latest.balance_eod if latest else (anchor.amount if anchor else None)
    source = (anchor.kind if anchor and anchor.day == as_of else "calculated") if amount is not None else "unknown"
    if source == "initial" and latest:
        source = "calculated"
    return {"amount": amount, "as_of": as_of, "source": source,
            "anchor_date": anchor.day if anchor else None, "anchor_source": anchor.kind if anchor else None,
            "initial_date": initial.day if initial else None, "initial_amount": initial.amount if initial else None,
            "first_operation_date": operations[0].op_date if operations else None,
            "unknown_operations": sum(op.balance_eod is None for op in operations)}


def set_initial_balance(session: Session, company: Company, day: date, amount: Decimal) -> dict:
    from app.services.history import refresh_history

    lock_company(session, company)
    first = session.scalar(select(Operation.op_date).where(Operation.company_id == company.id)
                           .order_by(Operation.op_date).limit(1))
    if day > date.today() or (first and day > first):
        raise BalanceError("Укажите дату не позже первого платежа: остаток задаётся на начало этого дня")
    point = initial_point(session, company)
    if point and point.day == day and point.amount == amount:
        return balance_status(session, company)
    if point:
        session.delete(point)
        session.flush()
    set_point(session, company, day, amount, "initial")
    if first:
        refresh_history(session, company)
    session.execute(update(Company).where(Company.id == company.id).values(data_version=Company.data_version + 1))
    session.commit()
    return balance_status(session, company)
