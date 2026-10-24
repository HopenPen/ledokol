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
from app.domain.types import ForecastResult, PlannedEvent
from app.services.classifier import get_classifier
from app.services.company_data import apply_user_categories, load_operations_frame
from app.services.events_mapping import to_domain_event  # noqa: F401 — реэкспорт для роутов
from app.services.snapshots import save_snapshot

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


def run_forecast(session: Session, company: Company, scenario: Scenario | None = None,
                 horizon: int | None = None) -> tuple[ForecastResult, CompanyModel]:
    s = get_settings()
    cm = company_model(session, company)
    events = planned_events(session, company, cm.fitted.as_of)
    result = forecast(cm.fitted, events, horizon=horizon or s.forecast_horizon, n_sims=s.forecast_sims,
                      seed=s.forecast_seed, threshold=float(company.min_balance), scenario=scenario,
                      data_warnings=cm.prep.quality.warnings)
    if scenario is None and horizon in (None, s.forecast_horizon):
        # Сохраняем только «официальный» прогноз: сценарии и черновики — это не обещание, их не сравниваем с фактом.
        save_snapshot(session, company, result, events)
    return result, cm


def quality_of(cm: CompanyModel) -> QualityReport:
    return cm.prep.quality


def run_preview(session: Session, company: Company, *, exclude_db_ids: set[str],
                extra_events: list[PlannedEvent], scenario: Scenario | None = None) -> ForecastResult:
    """Черновик правок: пересчёт без записи в БД и без снимка.

    Исключённые операции не удаляются из истории остатка (факт есть факт) — они просто не учат модель.
    Так предприниматель говорит «эта поставка была разовой, не жди её снова».
    """
    s = get_settings()
    cm = company_model(session, company)
    fitted = cm.fitted
    if exclude_db_ids:
        ops = cm.prep.ops[~cm.prep.ops["db_id"].isin(exclude_db_ids)]
        fitted = fit(ops, cm.prep.panel)
    events = planned_events(session, company, fitted.as_of) + extra_events
    return forecast(fitted, events, horizon=s.forecast_horizon, n_sims=s.forecast_sims, seed=s.forecast_seed,
                    threshold=float(company.min_balance), scenario=scenario, data_warnings=cm.prep.quality.warnings)
