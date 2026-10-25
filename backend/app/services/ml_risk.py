"""ML-оценка риска кассового разрыва моделью TabPFN: отдельный необязательный модуль.

Чем отличается от основного прогноза: основной прогноз (гибрид) считает остаток по дням и вероятность разрыва
симуляцией. Здесь готовая предобученная модель TabPFN v2 оценивает вероятность «разрыв будет в ближайшие 5, 10, 20, 30
дней» по признакам компании и по прогнозу гибрида. В проверке на 150 компаниях это давало более точные тревоги
(precision 0,63 против 0,53 при том же recall), но модель тяжёлая: лучше работает на видеокарте.

Модуль ничего не пишет в БД и не меняет основной прогноз.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from sqlalchemy.orm import Session

from app.db.models import Company
from app.domain.forecast import forecast
from app.domain.gap_features import HORIZON_DAYS, HORIZONS, build_context, gap_features
from app.domain.gap_predictor import GapPredictor, MlUnavailable, get_predictor  # noqa: F401 — get_predictor подменяют в тестах
from app.services.forecasting import company_model, planned_events

log = logging.getLogger("cashflow.ml_risk")

# Те же параметры, с которыми считались признаки при обучении (analytics/experiments/gap_classifier_v2.py).
FORECAST_SIMS, FORECAST_SEED = 150, 7

# Оценка занимает секунды, а при открытии экрана её просят снова и снова. Результат живёт, пока не изменились данные
# компании и её будущие события (ключ: компания, версия данных, подпись событий).
_results: OrderedDict[tuple, dict] = OrderedDict()
_results_lock = threading.Lock()
_RESULTS_MAX = 64


def ml_gap_risk(session: Session, company: Company) -> dict:
    """Вероятность разрыва по горизонтам для последнего дня выписки компании."""
    predictor = get_predictor()
    cm = company_model(session, company)                                  # LookupError, если операций нет
    ctx = build_context(cm.prep)
    base = {"model": {"name": "TabPFN v2", "device": predictor.device, "cv": predictor.meta.get("cv")}}
    if ctx.bal[-1] < 0:
        return {**base, "state": "already_negative", "horizons": []}
    events = planned_events(session, company, cm.fitted.as_of)            # события пользователя входят в признаки
    key = (company.id, company.data_version, tuple((e.event_date, round(e.amount, 2), e.direction.value, e.probability) for e in events))
    with _results_lock:
        if key in _results:
            _results.move_to_end(key)
            return _results[key]
    result = forecast(cm.fitted, events, horizon=HORIZON_DAYS, n_sims=FORECAST_SIMS, seed=FORECAST_SEED)
    feats = gap_features(ctx, result, predictor.industry_code(company.industry))
    proba = predictor.predict(feats)
    thresholds = predictor.meta.get("thresholds", {})
    horizons = []
    for h, p in zip(HORIZONS, proba):
        thr = thresholds.get(str(h), {})
        horizons.append({"days": h, "probability": round(float(p), 3),
                         "alert": bool(p >= thr["balanced"]) if "balanced" in thr else None,
                         "alert_high_recall": bool(p >= thr["high_recall"]) if "high_recall" in thr else None})
    out = {**base, "state": "ok", "horizons": horizons}
    with _results_lock:
        _results[key] = out
        while len(_results) > _RESULTS_MAX:
            _results.popitem(last=False)
    return out
