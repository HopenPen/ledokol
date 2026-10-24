"""Подход 4 (для сравнения в бэктесте): глобальная модель CatBoost для «статистической» части потока.

Почему CatBoost, а не LLM и не нейросеть:
- данных мало и они табличные (150 компаний × ~500 дней) — бустинг здесь сильнее и стабильнее нейросетей;
- категориальные признаки (отрасль, день недели) CatBoost ест без ручного кодирования;
- одна глобальная модель на всех компаниях «переносит знание» на компании с короткой историей и на
  новые компании скрытого датасета жюри — это ровно то, что нам нужно;
- MultiQuantile-лосс сразу даёт P10/P50/P90 — интервал без отдельного Монте-Карло.

Что прогнозирует: дневной поток слоёв B+C (розница + нерегулярное), а известные события (слой A: регулярные
платежи, налоги, ручной ввод) добавляются сверху так же, как в гибриде. Так сравнение честное: меняется
только способ прогнозировать «шумную» часть.

Постановка — прямая многошаговая: одна строка = (компания, точка отсечки, горизонт h). Признаки считаются
только по данным до отсечки, плюс календарь целевого дня. Утечки будущего нет по построению.

Статус: экспериментальный модуль. Встраивается в бэктест командой `cashflow train-catboost` (см. TODO.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.domain.categories import EXCLUDED_FROM_FORECAST
from app.domain.pipeline import PreparedCompany

QUANTILES = (0.1, 0.5, 0.9)
CAT_FEATURES = ["industry", "target_dow"]


def statistical_flow(prep: PreparedCompany, recurring_index: set[int] | None = None) -> pd.Series:
    """Дневной поток без денег владельца, переводов, налогов и (если передано) операций регулярных серий."""
    ops = prep.ops[prep.ops["quality"].isin(["ok", "after_gap"])]
    mask = ~ops["category"].isin(EXCLUDED_FROM_FORECAST | {"tax"})
    if recurring_index:
        mask &= ~ops.index.isin(list(recurring_index))
    flow = ops[mask].groupby("operation_date")["signed"].sum()
    return flow.reindex(pd.DatetimeIndex(prep.panel["date"]), fill_value=0.0)


def make_rows(flow: pd.Series, industry: str, horizon: int = 30, step: int = 5, min_history: int = 60,
              after_gap: np.ndarray | None = None) -> pd.DataFrame:
    """Обучающие строки по одной компании. Окна, задевающие «дыры» выписки, пропускаем."""
    vals, dates = flow.to_numpy(), flow.index
    rows = []
    for t in range(min_history, len(vals) - 1, step):
        hist = vals[: t + 1]
        feats = {
            "industry": industry,
            "mean_5": hist[-5:].mean(), "mean_20": hist[-20:].mean(), "mean_60": hist[-60:].mean(),
            "std_20": hist[-20:].std(), "share_pos_20": (hist[-20:] > 0).mean(),
            # TODO: заменить на среднее именно по дню недели целевого дня (сейчас — каждый 5-й день окна)
            "lag5_mean_8w": hist[::-5][:8].mean(),
        }
        for h in range(1, horizon + 1):
            if t + h >= len(vals) or (after_gap is not None and after_gap[t + h]):
                break
            d = dates[t + h]
            rows.append({**feats, "h": h, "target_dow": str(d.dayofweek), "target_dom": d.day,
                         "target_month": d.month, "days_to_28": (28 - d.day) % 31, "y": vals[t + h]})
    return pd.DataFrame(rows)


@dataclass(slots=True)
class CatBoostFlowModel:
    params: dict = field(default_factory=lambda: {
        "loss_function": "MultiQuantile:alpha=" + ",".join(map(str, QUANTILES)),
        "iterations": 800, "depth": 6, "learning_rate": 0.05, "random_seed": 7, "verbose": False,
    })
    model: object | None = None

    def fit(self, rows: pd.DataFrame) -> CatBoostFlowModel:
        from catboost import CatBoostRegressor, Pool  # опциональная зависимость: pip install ".[ml]"

        x, y = rows.drop(columns=["y"]), rows["y"]
        self.model = CatBoostRegressor(**self.params)
        self.model.fit(Pool(x, y, cat_features=CAT_FEATURES))
        return self

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Матрица (n, 3): P10, P50, P90 дневного потока."""
        if self.model is None:
            raise RuntimeError("Модель не обучена")
        return np.asarray(self.model.predict(rows.drop(columns=["y"], errors="ignore")))
