"""Все модели рядом: гибрид, CatBoost и их ансамбль. Только чтение, в БД ничего не пишется.

Пороги тревоги подобраны вложенной кросс-валидацией на 150 компаниях (analytics/model_evaluation.py):
гибрид 0,25, CatBoost 0,15, ансамбль 0,27 (среднее вероятностей гибрида и CatBoost).
"""
from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import Company
from app.domain.catboost_flow import get_flow_predictor
from app.domain.gap_predictor import MlUnavailable
from app.services.forecasting import run_forecast

THRESHOLDS = {"hybrid": 0.25, "catboost": 0.15, "ensemble": 0.27}
TITLES = {"hybrid": "Гибрид (статистика + симуляции)", "catboost": "CatBoost", "ensemble": "Ансамбль (гибрид + CatBoost)"}


def _model(key: str, probability: float, p50, p10, p90, days, below, p25, p75) -> dict:
    return {"key": key, "title": TITLES[key], "available": True, "probability": round(float(probability), 3),
            "threshold": THRESHOLDS[key], "alert": bool(probability >= THRESHOLDS[key]),
            "points": [{"date": d.isoformat(), "p10": round(float(a), 0), "p50": round(float(b), 0), "p90": round(float(c), 0),
                        "prob_below": round(float(r), 3), "p25": round(float(lo), 0), "p75": round(float(hi), 0)}
                       for d, a, b, c, r, lo, hi in zip(days, p10, p50, p90, below, p25, p75)]}


def compare_models(session: Session, company: Company) -> dict:
    result, cm = run_forecast(session, company, save=False)
    days = [p.day for p in result.points]
    hyb_below = np.array([p.prob_below for p in result.points])
    hyb_p = float(hyb_below.max())
    out = [_model("hybrid", hyb_p, [p.p50 for p in result.points], [p.p10 for p in result.points], [p.p90 for p in result.points], days, hyb_below,
                  [p.p25 for p in result.points], [p.p75 for p in result.points])]
    notes: list[str] = []
    try:
        cb = get_flow_predictor().predict(cm.prep, company.industry, days, threshold=float(company.min_balance))
        out.append(_model("catboost", cb.gap_probability, cb.p50, cb.quantiles[:, 1], cb.quantiles[:, -2], days, cb.prob_below, cb.quantiles[:, 2:4].mean(axis=1), cb.quantiles[:, 5:7].mean(axis=1)))
        ens = (hyb_p + cb.gap_probability) / 2
        mean = lambda a, b: (np.asarray(a) + np.asarray(b)) / 2    # noqa: E731
        out.append(_model("ensemble", ens, mean([p.p50 for p in result.points], cb.p50), mean([p.p10 for p in result.points], cb.quantiles[:, 1]),
                          mean([p.p90 for p in result.points], cb.quantiles[:, -2]), days, mean(hyb_below, cb.prob_below),
                          mean([p.p25 for p in result.points], cb.quantiles[:, 2:4].mean(axis=1)),
                          mean([p.p75 for p in result.points], cb.quantiles[:, 5:7].mean(axis=1))))
    except MlUnavailable as exc:
        out += [{"key": "catboost", "title": TITLES["catboost"], "available": False, "reason": str(exc)},
                {"key": "ensemble", "title": TITLES["ensemble"], "available": False, "reason": str(exc)}]
    if company.industry is None:
        notes.append("Отрасль компании не задана: качество CatBoost ниже.")
    return {"as_of": result.as_of.isoformat(), "last_balance": round(result.last_balance, 0), "threshold": float(company.min_balance),
            "models": out, "notes": notes}
