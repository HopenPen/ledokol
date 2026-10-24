"""Синхронизация с 1С и проверка контрагентов в ФНС.

Повторная синхронизация не плодит дублей: событие из 1С ищется по (company, source='1c', external_ref=Ref_Key).
Оплаченный с прошлого раза счёт закрывается статусом.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Company, PlannedEvent
from app.integrations.fns import CounterpartyStatus, FnsClient
from app.integrations.http import ResilientClient
from app.integrations.onec import OneCClient


@dataclass(slots=True)
class SyncResult:
    created: int
    updated: int
    closed: int


def sync_onec(session: Session, company: Company, as_of: date) -> SyncResult:
    s = get_settings()
    http = ResilientClient(s.onec_base_url, s.onec_token.get_secret_value(), timeout=s.integration_timeout_s)
    try:
        invoices = OneCClient(http).open_invoices(company.external_id, as_of)
    finally:
        http.close()
    existing = {e.external_ref: e for e in session.scalars(select(PlannedEvent).where(
        PlannedEvent.company_id == company.id, PlannedEvent.source == "1c"))}
    created = updated = 0
    seen: set[str] = set()
    for inv in invoices:
        seen.add(inv.ref)
        fields = dict(
            event_date=max(inv.due, as_of), amount=inv.amount, direction="out" if inv.incoming else "in",
            kind="invoice_in" if inv.incoming else "invoice_out",
            title=f"Счёт № {inv.number}: {inv.counterparty_name}",
            counterparty_key=inv.counterparty_inn or inv.counterparty_name, confidence="likely",
        )
        if inv.ref in existing:
            for k, v in fields.items():
                setattr(existing[inv.ref], k, v)
            updated += 1
        else:
            session.add(PlannedEvent(company_id=company.id, source="1c", external_ref=inv.ref, **fields))
            created += 1
    closed = 0
    for ref, ev in existing.items():          # счёта больше нет среди неоплаченных → оплачен/отменён в 1С
        if ref not in seen and ev.status == "expected":
            ev.status = "received"
            closed += 1
    # data_version не трогаем: выписка не менялась, модель не переобучаем — события лягут поверх готового fit.
    session.commit()
    return SyncResult(created, updated, closed)


def check_counterparties(session: Session, company: Company) -> list[CounterpartyStatus]:
    s = get_settings()
    events = list(session.scalars(select(PlannedEvent).where(
        PlannedEvent.company_id == company.id, PlannedEvent.status == "expected", PlannedEvent.direction == "in")))
    inns = sorted({e.counterparty_key for e in events if e.counterparty_key and e.counterparty_key.isdigit()})
    http = ResilientClient(s.fns_base_url, s.fns_token.get_secret_value(), timeout=s.integration_timeout_s)
    try:
        client = FnsClient(http)
        statuses = [client.check(inn) for inn in inns]
    finally:
        http.close()
    risky = {st.inn for st in statuses if st.risky}
    for e in events:
        if e.counterparty_key in risky:
            e.confidence = "unsure"   # вероятность оплаты 50% вместо 80% → риск разрыва пересчитается
    session.commit()
    return statuses
