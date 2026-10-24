"""Прогноз для компании из БД.

Дорогая часть (подготовка данных + fit) кешируется по (company.id, data_version). Новое ручное событие,
сценарий или смена порога не меняют data_version — пересчёт идёт от готовой модели за доли секунды.
Это и есть «обновление без полного пересчёта» из ТЗ и то, что жюри будет проверять: «ввели новую выплату —
посмотрели реакцию» (ответ ментора 24.10).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Company, PlannedEvent as PlannedEventRow
from app.domain.forecast import FittedModel, fit, forecast
from app.domain.ingest import QualityReport
from app.domain.pipeline import PreparedCompany, prepare_company
from app.domain.scenarios import Scenario
from app.domain.types import CONFIDENCE_PROB, Confidence, Direction, EventSource, ForecastResult, PlannedEvent
from app.services.classifier import get_classifier
from app.services.company_data import apply_user_categories, load_operations_frame

_KIND_TO_CATEGORY = {"invoice_out": "client_payment", "invoice_in": "suppliers", "tax": "tax"}


@dataclass(slots=True)
class CompanyModel:
    prep: PreparedCompany
    fitted: FittedModel


class _ModelCache:
    """Маленький потокобезопасный LRU. Для прототипа хватает памяти процесса; в бою — Redis с тем же ключом."""

    def __init__(self, size: int = 64) -> None:
        self._data: OrderedDict[tuple[str, int], CompanyModel] = OrderedDict()
        self._size, self._lock = size, threading.Lock()

    def get(self, key: tuple[str, int]) -> CompanyModel | None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
        return None

    def put(self, key: tuple[str, int], value: CompanyModel) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._size:
                self._data.popitem(last=False)


_cache = _ModelCache()


def company_model(session: Session, company: Company) -> CompanyModel:
    key = (company.id, company.data_version)
    if (hit := _cache.get(key)) is not None:
        return hit
    frame = load_operations_frame(session, company)
    if frame.empty:
        raise LookupError("no_operations")
    prep = prepare_company(frame, get_classifier())
    prep.ops = apply_user_categories(prep.ops)
    model = CompanyModel(prep=prep, fitted=fit(prep.ops, prep.panel))
    _cache.put(key, model)
    return model


def planned_events(session: Session, company: Company, after: date) -> list[PlannedEvent]:
    rows = session.scalars(select(PlannedEventRow).where(
        PlannedEventRow.company_id == company.id, PlannedEventRow.status == "expected",
        PlannedEventRow.event_date > after))
    return [to_domain_event(r) for r in rows]


def to_domain_event(r: PlannedEventRow) -> PlannedEvent:
    source = {"manual": EventSource.MANUAL, "1c": EventSource.ONEC}.get(r.source, EventSource.MANUAL)
    return PlannedEvent(
        event_date=r.event_date, amount=float(r.amount), direction=Direction(r.direction), title=r.title,
        category=_KIND_TO_CATEGORY.get(r.kind, "other"), source=source,
        probability=CONFIDENCE_PROB[Confidence(r.confidence)],
        date_jitter_days=3 if r.kind == "invoice_out" else 0,   # клиенты платят по счетам с задержкой
        counterparty_key=r.counterparty_key, ref=r.id,
    )


def run_forecast(session: Session, company: Company, scenario: Scenario | None = None,
                 horizon: int | None = None) -> tuple[ForecastResult, CompanyModel]:
    s = get_settings()
    cm = company_model(session, company)
    events = planned_events(session, company, cm.fitted.as_of)
    result = forecast(cm.fitted, events, horizon=horizon or s.forecast_horizon, n_sims=s.forecast_sims,
                      seed=s.forecast_seed, threshold=float(company.min_balance), scenario=scenario,
                      data_warnings=cm.prep.quality.warnings)
    return result, cm


def quality_of(cm: CompanyModel) -> QualityReport:
    return cm.prep.quality
