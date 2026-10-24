"""Строка planned_events из БД → доменное событие прогноза. Отдельный модуль, чтобы им пользовались и прогноз,
и импорт выписки (сверка план-факт) без циклических импортов."""
from __future__ import annotations

from app.db.models import PlannedEvent as PlannedEventRow
from app.domain.types import CONFIDENCE_PROB, Confidence, Direction, EventSource, PlannedEvent

_KIND_TO_CATEGORY = {"invoice_out": "client_payment", "invoice_in": "suppliers", "tax": "tax"}


def to_domain_event(r: PlannedEventRow) -> PlannedEvent:
    source = {"manual": EventSource.MANUAL, "1c": EventSource.ONEC}.get(r.source, EventSource.MANUAL)
    return PlannedEvent(
        event_date=r.event_date, amount=float(r.amount), direction=Direction(r.direction), title=r.title,
        category=_KIND_TO_CATEGORY.get(r.kind, "other"), source=source,
        probability=CONFIDENCE_PROB[Confidence(r.confidence)],
        date_jitter_days=3 if r.kind == "invoice_out" else 0,   # клиенты платят по счетам с задержкой
        counterparty_key=r.counterparty_key, ref=r.id,
    )
