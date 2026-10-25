"""Загрузка выписки: адаптер → привязка счёта → операции → общая обработка истории."""
from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import BankAccount, Company, Operation, StatementImport, User
from app.domain.ingest import QualityReport, StatementFormatError
from app.importers import ParsedImport, parse_statement
from app.services.balances import lock_company, set_point
from app.services.history import refresh_history


@dataclass(slots=True)
class ImportResult:
    company: Company
    rows_total: int
    rows_new: int
    already_imported: bool
    quality: QualityReport
    rows_matched: int = 0


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
            lock_company(session, target)
            journal = session.scalar(select(StatementImport).where(StatementImport.company_id == target.id,
                                                                   StatementImport.sha256 == digest))
            if journal:
                results.append(ImportResult(target, len(part), 0, True, QualityReport(rows_total=len(part))))
                continue
            existing = set(session.scalars(select(Operation.source_operation_id).where(Operation.company_id == target.id)))
            fresh = part[~part["operation_id"].isin(existing)].drop_duplicates("operation_id")
            for day, day_rows in part.groupby("operation_date"):
                set_point(session, target, day.date(), Decimal(str(day_rows.iloc[0]["balance_eod"])), "statement")
            created, matched = _merge_operations(session, target, fresh)
            session.flush()
            quality = refresh_history(session, target)
            session.add(StatementImport(company_id=target.id, sha256=digest, rows_total=len(part), rows_new=created))
            session.execute(update(Company).where(Company.id == target.id).values(data_version=Company.data_version + 1))
            results.append(ImportResult(target, len(part), created, False, quality, matched))
        if not results:
            raise StatementFormatError("В файле нет платежей выбранной компании")
        rejected = int(parsed.frame.attrs.get("rows_rejected", 0))
        if rejected:
            lines = ", ".join(map(str, parsed.frame.attrs.get("rejected_lines", [])))
            fields = ", ".join(parsed.frame.attrs.get("invalid_fields", []))
            for result in results:
                result.quality.rows_rejected = rejected
                result.quality.warnings.append(
                    f"В файле пропущено строк: {rejected}. Номера записей CSV: {lines}. Проверьте поля: {fields}")
        session.commit()
        return results
    except Exception:
        session.rollback()
        raise


def _normalize(value):
    return " ".join(str(value or "").casefold().split())


def _signature(day, amount, direction, purpose):
    return day, Decimal(str(amount)), direction, _normalize(purpose)


def _same_counterparty(inn_a, name_a, inn_b, name_b):
    return inn_a == inn_b if inn_a and inn_b else _normalize(name_a) == _normalize(name_b)


def _merge_operations(session: Session, company: Company, fresh) -> tuple[int, int]:
    """Сначала точные совпадения, затем однозначные ручные платежи без назначения."""
    manual = defaultdict(list)
    without_purpose = []
    for op in session.scalars(select(Operation).where(Operation.company_id == company.id,
                                                      Operation.source_operation_id.startswith("manual:"))
                             .order_by(Operation.source_operation_id)):
        if _normalize(op.purpose):
            manual[_signature(op.op_date, op.amount, op.direction, op.purpose)].append(op)
        else:
            without_purpose.append(op)
    incoming = defaultdict(list)
    for row in fresh.itertuples(index=False):
        incoming[_signature(row.operation_date.date(), row.amount, row.direction, row.payment_purpose)].append(row)
    created = matched = 0
    pending = []
    for signature, rows in incoming.items():
        available = manual.get(signature, []).copy()
        for index, row in enumerate(rows):
            candidates = [op for op in available if _same_counterparty(
                op.counterparty_inn, op.counterparty_name, row.counterparty_inn, row.counterparty_name)]
            remaining = [r for r in rows[index:] if _same_counterparty(
                r.counterparty_inn, r.counterparty_name, row.counterparty_inn, row.counterparty_name)]
            if len(candidates) > len(remaining):
                raise StatementFormatError("В выписке найден платёж, которому соответствуют несколько одинаковых ручных платежей. "
                                           "Загрузите полную выписку за этот день для однозначной сверки.")
            if candidates:
                operation = candidates[0]
                available.remove(operation)
                matched += 1
            else:
                pending.append(row)
                continue
            _apply_statement_row(operation, row)
    candidates = {row.operation_id: [op for op in without_purpose if _same_payment_without_purpose(op, row)]
                  for row in pending}
    uses = Counter(op.id for options in candidates.values() for op in options)
    for row in pending:
        options = candidates[row.operation_id]
        if len(options) > 1 or any(uses[op.id] > 1 for op in options):
            raise StatementFormatError("Нельзя однозначно сопоставить ручной платёж без назначения с выпиской: "
                                       "совпадают несколько операций по дате, сумме, направлению и контрагенту. "
                                       "Проверьте ручные платежи и выписку.")
        if options:
            operation = options[0]
            matched += 1
        else:
            operation = Operation(company_id=company.id)
            session.add(operation)
            created += 1
        _apply_statement_row(operation, row)
    return created, matched


def _same_payment_without_purpose(operation: Operation, row) -> bool:
    return (operation.op_date == row.operation_date.date() and operation.amount == Decimal(str(row.amount))
            and operation.direction == row.direction and _same_counterparty(
                operation.counterparty_inn, operation.counterparty_name, row.counterparty_inn, row.counterparty_name))


def _apply_statement_row(operation: Operation, row) -> None:
    operation.source_operation_id = row.operation_id
    operation.op_date = row.operation_date.date()
    operation.amount, operation.direction = Decimal(str(row.amount)), row.direction
    operation.counterparty_inn, operation.counterparty_name = row.counterparty_inn or None, row.counterparty_name
    operation.purpose = row.payment_purpose
    operation.balance_eod = Decimal(str(row.balance_eod))


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
