"""Прогноз остатка моделью CatBoost v2 (накопленный поток за h дней, две модели: среднее и 9 квантилей).

Признаки и целевая переменная те же, что при обучении (`ml_flow.make_cum_rows`); отличие одно: в обучении цель известна,
здесь отсечка — последний день выписки, а будущие даты берутся из рабочего календаря. Без пакета catboost или файлов
модели бросается MlUnavailable.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from app.core.config import get_settings
from app.domain.gap_predictor import MlUnavailable
from app.domain.ml_flow import CAT_FEATURES, NON_FEATURES, _tax_days, operational_flow, scale_of
from app.domain.pipeline import PreparedCompany

_lock = threading.Lock()
_cache: dict[str, CatBoostFlowPredictor] = {}


@dataclass
class FlowForecast:
    days: list[date]
    p50: np.ndarray            # остаток, ₽
    quantiles: np.ndarray      # (h, 9) остаток по квантилям, ₽
    prob_below: np.ndarray     # вероятность остатка < порога по дням

    @property
    def gap_probability(self) -> float:
        return float(self.prob_below.max())


@dataclass
class CatBoostFlowPredictor:
    mean: object
    quant: object
    meta: dict

    @property
    def qs(self) -> list[float]:
        return self.meta["quantiles"]

    def _prob_below(self, q: np.ndarray, thr: float) -> np.ndarray:
        qs, out = self.qs, []
        for row in q:
            if row[0] <= thr <= row[-1]:
                out.append(np.interp(thr, row, qs))
            else:                                  # за краями квантилей — нормальный хвост
                sigma = max((row[-1] - row[0]) / (2 * norm.ppf(qs[-1])), 1e-9)
                p = norm.cdf((thr - row[qs.index(0.5)]) / sigma)
                out.append(min(p, qs[0]) if thr < row[0] else max(p, qs[-1]))
        return np.array(out)

    def predict(self, prep: PreparedCompany, industry: str | None, days: list[date], threshold: float = 0.0) -> FlowForecast:
        flow = operational_flow(prep)
        vals = flow.to_numpy(dtype=float)
        dates = flow.index
        t = len(vals) - 1
        if t < 60:
            raise MlUnavailable("Мало истории для CatBoost: нужно не меньше 60 рабочих дней.")
        cum = np.r_[0.0, np.cumsum(vals)]
        sc = scale_of(vals[-60:])
        hist = vals / sc
        base = {"industry": industry or "unknown", "source": "case", "mean_5": hist[-5:].mean(), "mean_20": hist[-20:].mean(),
                "mean_60": hist[-60:].mean(), "std_20": hist[-20:].std(), "share_pos_20": (hist[-20:] > 0).mean(),
                "cutoff_dom": dates[t].day}
        future = pd.DatetimeIndex(pd.to_datetime(days))
        tax = _tax_days(dates.append(future))
        rows = []
        for h, d in enumerate(future, start=1):
            lag = 21 * int(np.ceil(h / 21))
            end = t + h
            lag1 = (cum[end - lag + 1] - cum[t - lag + 1]) / sc if t - lag >= 0 else np.nan
            lag2 = (cum[end - lag - 20] - cum[t - lag - 20]) / sc if t - lag - 21 >= 0 else np.nan
            rows.append({**base, "h": h, "target_dow": str(d.day_of_week), "target_dom": d.day, "target_month": d.month,
                         "n_tax_days": int(tax[t + 1: end + 1].sum()), "mean60_x_h": base["mean_60"] * h, "lag1": lag1, "lag2": lag2})
        x = pd.DataFrame(rows)[[c for c in self.mean.feature_names_]]
        b0 = float(prep.panel["balance"].iloc[-1])
        p50 = b0 + sc * self.mean.predict(x)
        q = b0 + sc * np.sort(self.quant.predict(x), axis=1)
        return FlowForecast(days=list(days), p50=p50, quantiles=q, prob_below=self._prob_below(q, threshold))


def get_flow_predictor() -> CatBoostFlowPredictor:
    folder = Path(get_settings().ml_flow_dir)
    key = str(folder.resolve())
    with _lock:
        if key in _cache:
            return _cache[key]
        if not all((folder / f).exists() for f in ("mean.cbm", "quantile.cbm", "meta.json")):
            raise MlUnavailable("Модель CatBoost не найдена: нет файлов в папке models/catboost_flow.")
        try:
            from catboost import CatBoostRegressor
        except ImportError as exc:
            raise MlUnavailable("Не установлен пакет catboost (uv sync --extra ml).") from exc
        pred = CatBoostFlowPredictor(CatBoostRegressor().load_model(str(folder / "mean.cbm")),
                                     CatBoostRegressor().load_model(str(folder / "quantile.cbm")),
                                     json.loads((folder / "meta.json").read_text(encoding="utf-8")))
        _cache[key] = pred
        return pred
