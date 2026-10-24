"""Снимки прогнозов: сохраняем «что обещали», чтобы потом сравнить с фактом.

Что будет, если прогноз пересчитать дважды на тех же данных? Тот же снимок: ключ — (компания, версия выписки,
хеш ожидаемых событий). Новое событие или новая выписка → новый снимок. Гонку двух запросов ловит UNIQUE в БД.
"""
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Company, ForecastPointRow, ForecastRun
from app.domain.forecast import MODEL_VERSION
from app.domain.types import ForecastResult, PlannedEvent


def events_hash(events: list[PlannedEvent]) -> str:
    """Хеш ручных и 1С-событий, от которых зависит прогноз. Порядок не важен."""
    keys = sorted(f"{e.ref}|{e.event_date}|{e.amount:.2f}|{e.direction.value}|{e.probability}" for e in events)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def _find(session: Session, company: Company, h: str) -> ForecastRun | None:
    return session.scalar(select(ForecastRun).where(
        ForecastRun.company_id == company.id, ForecastRun.data_version == company.data_version,
        ForecastRun.events_hash == h))


def save_snapshot(session: Session, company: Company, result: ForecastResult,
                  planned: list[PlannedEvent]) -> ForecastRun:
    h = events_hash(planned)
    if (found := _find(session, company, h)) is not None:
        return found
    run = ForecastRun(company_id=company.id, as_of=result.as_of, data_version=company.data_version,
                      events_hash=h, model_version=MODEL_VERSION, horizon=len(result.points))
    run.points = [ForecastPointRow(day=p.day, p10=_money(p.p10), p50=_money(p.p50), p90=_money(p.p90))
                  for p in result.points]
    session.add(run)
    try:
        session.commit()
    except IntegrityError:   # параллельный запрос успел сохранить тот же снимок
        session.rollback()
        return _find(session, company, h)
    return run


def runs_before(session: Session, company: Company, as_of: date) -> list[ForecastRun]:
    """Снимки по более старой выписке — с ними сравниваем свежий факт. Новые сверху."""
    return list(session.scalars(
        select(ForecastRun).where(ForecastRun.company_id == company.id, ForecastRun.as_of < as_of)
        .order_by(ForecastRun.as_of.desc(), ForecastRun.created_at.desc())))


def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))
