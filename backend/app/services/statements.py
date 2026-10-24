"""Загрузка выписки: адаптер → привязка счёта → операции → общая обработка истории."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import BankAccount, Company, Operation, StatementImport, User
from app.domain.ingest import QualityReport, StatementFormatError
from app.importers import ParsedImport, parse_statement
from app.services.history import refresh_history


@dataclass(slots=True)
class ImportResult:
    company: Company
    rows_total: int
    rows_new: int
    already_imported: bool
    quality: QualityReport


def import_statement(session: Session, user: User, raw: bytes, company: Company | None = None,
                     filename: str = "statement.csv") -> list[ImportResult]:
    parsed = parse_statement(raw, filename)
    digest, results = hashlib.sha256(raw).hexdigest(), []
    try:
        for external, part in parsed.frame.groupby("company_id", sort=True):
            external = str(external)
            if company is not None and external not in parsed.accounts and external != company.external_id:
                if company.external_id.startswith("manual:") and parsed.frame["company_id"].nunique() == 1:
                    if not 1 <= len(external) <= 32 or session.scalar(select(Company).where(
                            Company.owner_id == user.id, Company.external_id == external)):
                        raise StatementFormatError("Компания из CSV уже существует или имеет некорректный идентификатор")
                    company.external_id = external
                else:
                    continue
            target = _target(session, user, external, parsed, company)
            journal = session.scalar(select(StatementImport).where(StatementImport.company_id == target.id,
                                                                   StatementImport.sha256 == digest))
            if journal:
                results.append(ImportResult(target, len(part), 0, True, QualityReport(rows_total=len(part))))
                continue
            existing = set(session.scalars(select(Operation.source_operation_id).where(Operation.company_id == target.id)))
            fresh = part[~part["operation_id"].isin(existing)].drop_duplicates("operation_id")
            for day, day_rows in fresh.groupby("operation_date"):
                session.execute(update(Operation).where(Operation.company_id == target.id, Operation.op_date == day.date())
                                .values(balance_eod=Decimal(str(day_rows.iloc[0]["balance_eod"]))))
            session.add_all([Operation(
                company_id=target.id, source_operation_id=r.operation_id, op_date=r.operation_date.date(),
                amount=Decimal(str(r.amount)), direction=r.direction, counterparty_inn=r.counterparty_inn or None,
                counterparty_name=r.counterparty_name, purpose=r.payment_purpose, balance_eod=Decimal(str(r.balance_eod)))
                for r in fresh.itertuples(index=False)])
            session.flush()
            quality = refresh_history(session, target)
            session.add(StatementImport(company_id=target.id, sha256=digest, rows_total=len(part), rows_new=len(fresh)))
            session.execute(update(Company).where(Company.id == target.id).values(data_version=Company.data_version + 1))
            results.append(ImportResult(target, len(part), len(fresh), False, quality))
        if not results:
            raise StatementFormatError("В файле нет платежей выбранной компании")
        session.commit()
        return results
    except Exception:
        session.rollback()
        raise


def _target(session: Session, user: User, external: str, parsed: ParsedImport, selected: Company | None) -> Company:
    account = parsed.accounts.get(external)
    binding = session.scalar(select(BankAccount).where(BankAccount.owner_id == user.id, BankAccount.number == account)) if account else None
    if binding and selected and binding.company_id != selected.id:
        raise StatementFormatError("Этот банковский счёт уже связан с другой компанией")
    target = selected or (session.get(Company, binding.company_id) if binding else None)
    if target is None:
        if not 1 <= len(external) <= 32:
            raise StatementFormatError("Идентификатор компании должен содержать от 1 до 32 символов")
        target = session.scalar(select(Company).where(Company.owner_id == user.id, Company.external_id == external))
    if target is None:
        target = Company(owner_id=user.id, external_id=external, name=parsed.names.get(external) or f"Компания {external}")
        session.add(target)
        session.flush()
    if account:
        current = session.get(BankAccount, target.id)
        if current and current.number != account:
            raise StatementFormatError("Для компании уже выбран другой счёт; создайте отдельную компанию для второго счёта")
        if current is None:
            session.add(BankAccount(company_id=target.id, owner_id=user.id, number=account))
            session.flush()
    return target
