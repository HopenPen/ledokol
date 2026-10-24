"""Ручные события с ключом идемпотентности.

Что будет, если клиент дважды отправит «клиент обещал 300 000 ₽ 20-го» (двойной клик, ретрай сети)?
Тот же Idempotency-Key + тот же запрос → вернём уже созданное событие. Тот же ключ + другой запрос → 409.
Ключ и событие пишутся одной строкой в одной транзакции, а UNIQUE в БД ловит гонку двух параллельных запросов.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Company, PlannedEvent


class IdempotencyConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class NewEvent:
    event_date: date
    amount: Decimal
    direction: str
    kind: str
    title: str
    confidence: str = "likely"
    counterparty_key: str | None = None

    def fingerprint(self) -> str:
        payload = json.dumps({k: str(v) for k, v in asdict(self).items()}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()


def create_manual_event(session: Session, company: Company, data: NewEvent,
                        idempotency_key: str | None) -> tuple[PlannedEvent, bool]:
    """Возвращает (событие, создано_сейчас)."""
    fp = data.fingerprint()
    if idempotency_key:
        existing = session.scalar(select(PlannedEvent).where(PlannedEvent.company_id == company.id,
                                                             PlannedEvent.idempotency_key == idempotency_key))
        if existing:
            if existing.request_hash != fp:
                raise IdempotencyConflict
            return existing, False
    ev = PlannedEvent(company_id=company.id, source="manual", idempotency_key=idempotency_key, request_hash=fp,
                      event_date=data.event_date, amount=data.amount, direction=data.direction, kind=data.kind,
                      title=data.title, confidence=data.confidence, counterparty_key=data.counterparty_key)
    session.add(ev)
    try:
        session.commit()
    except IntegrityError:  # параллельный запрос с тем же ключом успел раньше
        session.rollback()
        existing = session.scalar(select(PlannedEvent).where(PlannedEvent.company_id == company.id,
                                                             PlannedEvent.idempotency_key == idempotency_key))
        if existing is None or existing.request_hash != fp:
            raise IdempotencyConflict from None
        return existing, False
    return ev, True


def cancel_event(session: Session, event: PlannedEvent) -> None:
    """Отмена — смена статуса, а не удаление: в план-факте должно быть видно, что событие было и его отменили."""
    event.status = "cancelled"
    session.commit()
