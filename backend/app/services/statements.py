"""Загрузка выписки в БД.

Идемпотентность (что будет, если загрузить дважды?):
- тот же файл целиком → находим по sha256 и ничего не делаем;
- файл с частично новыми строками (дозагрузка за неделю) → вставляем только новые operation_id.
После вставки заново размечаем качество и категории по всей истории компании: дубль определяется сверкой
с остатком, а для этого нужны соседние дни. Категории, которые пользователь поправил руками, не трогаем.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Operation, StatementImport, User
from app.domain.ingest import QualityReport, read_statement
from app.domain.pipeline import prepare_company
from app.services.company_data import load_operations_frame
from app.services.classifier import get_classifier

log = logging.getLogger("cashflow.statements")


@dataclass(slots=True)
class ImportResult:
    company: Company
    rows_total: int
    rows_new: int
    already_imported: bool
    quality: QualityReport


def import_statement(session: Session, user: User, raw: bytes, company: Company | None = None) -> list[ImportResult]:
    """Если company не задана — создаём компании по company_id из файла (сценарий «загрузил выписку → сразу прогноз»)."""
    digest = hashlib.sha256(raw).hexdigest()
    df = read_statement(raw)
    results: list[ImportResult] = []
    for external_id, part in df.groupby("company_id", sort=True):
        target = company if company is not None else _get_or_create_company(session, user, str(external_id), part)
        if company is not None and str(external_id) != company.external_id:
            continue  # в общий файл могут попасть чужие компании — берём только свою
        if session.scalar(select(StatementImport).where(StatementImport.company_id == target.id,
                                                        StatementImport.sha256 == digest)):
            results.append(ImportResult(target, len(part), 0, True, QualityReport(rows_total=len(part))))
            continue
        rows_new = _insert_new_operations(session, target, part)
        session.add(StatementImport(company_id=target.id, sha256=digest, rows_total=len(part), rows_new=rows_new))
        quality = _relabel(session, target)
        target.data_version += 1
        results.append(ImportResult(target, len(part), rows_new, False, quality))
        log.info("statement_imported", extra={"company_id": target.id, "rows": rows_new})
    session.commit()
    return results


def _get_or_create_company(session: Session, user: User, external_id: str, part: pd.DataFrame) -> Company:
    found = session.scalar(select(Company).where(Company.owner_id == user.id, Company.external_id == external_id))
    if found:
        return found
    company = Company(owner_id=user.id, external_id=external_id, name=f"Компания {external_id}")
    session.add(company)
    session.flush()
    return company


def _insert_new_operations(session: Session, company: Company, part: pd.DataFrame) -> int:
    existing = set(session.scalars(select(Operation.source_operation_id).where(Operation.company_id == company.id)))
    fresh = part[~part["operation_id"].isin(existing)]
    session.add_all([
        Operation(
            company_id=company.id, source_operation_id=r.operation_id, op_date=r.operation_date.date(),
            amount=Decimal(str(r.amount)), direction=r.direction,
            counterparty_inn=r.counterparty_inn or None, counterparty_name=r.counterparty_name,
            purpose=r.payment_purpose, balance_eod=Decimal(str(r.balance_eod)),
        )
        for r in fresh.itertuples(index=False)
    ])
    session.flush()
    return len(fresh)


def _relabel(session: Session, company: Company) -> QualityReport:
    frame, rows = load_operations_frame(session, company, with_rows=True)
    prep = prepare_company(frame, get_classifier())
    by_source = prep.ops.set_index("operation_id")
    for op in rows:
        lab = by_source.loc[op.source_operation_id]
        op.quality = lab["quality"]
        if op.category_source != "user":   # ручную правку пользователя модель не перетирает
            op.category, op.category_source, op.confidence = lab["category"], lab["category_source"], float(lab["confidence"])
    return prep.quality
