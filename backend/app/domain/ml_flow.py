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

Внешние датасеты (MBD Сбера, продажи 1С) смешиваются без дисбаланса: цель в долях масштаба компании,
признак source, отбор похожих окон и веса — см. docs/external_data.md.

Статус: экспериментальный модуль, в бэктест ещё не подключён (docs/DEVELOPER_TZ.md, задача 3.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.domain.categories import EXCLUDED_FROM_FORECAST
from app.domain.pipeline import PreparedCompany

QUANTILES = (0.1, 0.5, 0.9)
CAT_FEATURES = ["industry", "target_dow", "source"]
NON_FEATURES = ["y", "weight", "company", "cutoff", "scale"]   # служебные колонки; scale — чтобы вернуть прогноз в рубли


def statistical_flow(prep: PreparedCompany, recurring_index: set[int] | None = None) -> pd.Series:
    """Дневной поток без денег владельца, переводов, налогов и (если передано) операций регулярных серий."""
    ops = prep.ops[prep.ops["quality"].isin(["ok", "after_gap"])]
    mask = ~ops["category"].isin(EXCLUDED_FROM_FORECAST | {"tax"})
    if recurring_index:
        mask &= ~ops.index.isin(list(recurring_index))
    flow = ops[mask].groupby("operation_date")["signed"].sum()
    return flow.reindex(pd.DatetimeIndex(prep.panel["date"]), fill_value=0.0)


def scale_of(flow: pd.Series | np.ndarray) -> float:
    """Масштаб компании: средний модуль дневного потока. Цель и признаки делим на него — так компании с оборотом
    50 тыс. и 50 млн в день сопоставимы, и крупные внешние клиенты не перетягивают модель на себя."""
    v = np.abs(np.asarray(flow, dtype=float))
    return float(v.mean()) if v.size and v.mean() > 0 else 1.0


def make_rows(flow: pd.Series, industry: str, horizon: int = 30, step: int = 5, min_history: int = 60,
              after_gap: np.ndarray | None = None, source: str = "case", company: str = "",
              horizons: list[int] | None = None, cutoff_range: tuple | None = None) -> pd.DataFrame:
    """Обучающие строки по одной компании. Окна, задевающие «дыры» выписки, пропускаем.

    Всё в долях масштаба компании (scale_of по истории до отсечки) — чтобы смешивать с внешними датасетами.
    horizons — какие горизонты брать (для обучения хватает выборки, для оценки нужны все 1..horizon);
    cutoff_range — (с, по) даты отсечек, чтобы обучение и проверка не пересекались во времени.
    """
    vals, dates = flow.to_numpy(dtype=float), flow.index
    rows = []
    hs = horizons or list(range(1, horizon + 1))
    for t in range(min_history, len(vals) - 1, step):
        if cutoff_range is not None and not (cutoff_range[0] <= dates[t] <= cutoff_range[1]):
            continue
        hist = vals[: t + 1]
        sc = scale_of(hist[-60:])
        h_n = hist / sc
        dows = dates[: t + 1].day_of_week
        feats = {
            "industry": industry, "source": source, "company": company,
            "mean_5": h_n[-5:].mean(), "mean_20": h_n[-20:].mean(), "mean_60": h_n[-60:].mean(),
            "std_20": h_n[-20:].std(), "share_pos_20": (h_n[-20:] > 0).mean(),
        }
        for h in hs:
            if t + h >= len(vals) or (after_gap is not None and after_gap[t + 1: t + h + 1].any()):
                break
            d = dates[t + h]
            same_dow = h_n[-40:][dows[-40:] == d.day_of_week]   # тот же день недели за последние ~8 недель
            rows.append({**feats, "cutoff": dates[t], "scale": sc, "h": h, "target_dow": str(d.day_of_week), "target_dom": d.day,
                         "target_month": d.month, "days_to_28": (28 - d.day) % 31,
                         "same_dow_mean_8w": same_dow.mean() if same_dow.size else 0.0,
                         "y": vals[t + h] / sc})
    return pd.DataFrame(rows)


def operational_flow(prep: PreparedCompany) -> pd.Series:
    """Весь дневной поток, который прогноз обязан предсказать: без денег владельца, своих переводов и кредитов.

    В отличие от statistical_flow, здесь остаются налоги и регулярные платежи — для v2 модель учит всё сразу.
    """
    ops = prep.ops[prep.ops["quality"].isin(["ok", "after_gap"]) & ~prep.ops["category"].isin(EXCLUDED_FROM_FORECAST)]
    flow = ops.groupby("operation_date")["signed"].sum()
    return flow.reindex(pd.DatetimeIndex(prep.panel["date"]), fill_value=0.0)


def _tax_days(dates: pd.DatetimeIndex) -> np.ndarray:
    """Первый рабочий день с числом ≥ 28 в каждом месяце — туда ложится ЕНП (28-е с переносом)."""
    key = dates.year * 12 + dates.month
    first = pd.Series(dates.day >= 28).groupby(key).transform(lambda s: s & ~s.shift(fill_value=False).cummax())
    return first.to_numpy()


def make_cum_rows(flow: pd.Series, industry: str, horizon: int = 30, step: int = 3, min_history: int = 60,
                  after_gap: np.ndarray | None = None, source: str = "case", company: str = "",
                  horizons: list[int] | None = None, positions: list[int] | None = None,
                  max_target_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """v2: строка = (компания, отсечка, h), цель — НАКОПЛЕННЫЙ поток за h рабочих дней в долях масштаба.

    Почему так. v1 учила медиану дневного потока, а остаток — это сумма потоков: сумма медиан ≠ медиана суммы,
    и на горизонте 30 ошибка остатка выходила хуже наивного прогноза. Здесь модель сразу учит то, что нужно
    остатку: остаток через h дней = остаток сегодня + scale × прогноз.

    Признаки «то же окно месяц и два назад» (lag1/lag2) переносят ритм зарплат, аренды и налогов. Сдвиг кратен
    21 рабочему дню и не меньше h — окно лага целиком в прошлом, утечки нет.
    positions — явные индексы отсечек (для оценки на тех же окнах, что бэктест);
    max_target_date — обучающие окна должны закончиться раньше начала проверки (иначе утечка по времени).
    """
    vals, dates = flow.to_numpy(dtype=float), flow.index
    cum = np.r_[0.0, np.cumsum(vals)]
    tax = _tax_days(dates)
    hs = horizons or list(range(1, horizon + 1))
    ts = positions if positions is not None else range(min_history, len(vals) - 1, step)
    rows = []
    for t in ts:
        hist = vals[: t + 1]
        sc = scale_of(hist[-60:])
        h_n = hist / sc
        base = {
            "industry": industry, "source": source, "company": company, "cutoff": dates[t], "scale": sc,
            "mean_5": h_n[-5:].mean(), "mean_20": h_n[-20:].mean(), "mean_60": h_n[-60:].mean(),
            "std_20": h_n[-20:].std(), "share_pos_20": (h_n[-20:] > 0).mean(),
            "cutoff_dom": dates[t].day,
        }
        for h in hs:
            end = t + h
            if end >= len(vals) or (after_gap is not None and after_gap[t + 1: end + 1].any()):
                break
            if max_target_date is not None and dates[end] >= max_target_date:
                break
            lag = 21 * int(np.ceil(h / 21))
            lag1 = (cum[end - lag + 1] - cum[t - lag + 1]) / sc if t - lag >= 0 else np.nan
            lag2 = (cum[end - lag - 20] - cum[t - lag - 20]) / sc if t - lag - 21 >= 0 else np.nan
            d = dates[end]
            rows.append({**base, "h": h, "target_dow": str(d.day_of_week), "target_dom": d.day,
                         "target_month": d.month, "n_tax_days": int(tax[t + 1: end + 1].sum()),
                         "mean60_x_h": base["mean_60"] * h, "lag1": lag1, "lag2": lag2,
                         "y": (cum[end + 1] - cum[t + 1]) / sc})
    return pd.DataFrame(rows)


def mix_weights(rows: pd.DataFrame, case_share: float = 0.5) -> pd.Series:
    """Веса строк: суммарный вес наших (source=case) — не меньше case_share, сколько бы ни было внешних."""
    is_case = rows["source"].eq("case")
    n_case, n_ext = int(is_case.sum()), int((~is_case).sum())
    if n_ext == 0 or n_case == 0:
        return pd.Series(1.0, index=rows.index)
    w_ext = (1 - case_share) / case_share * n_case / n_ext   # тогда Σw_case / Σw = case_share
    return pd.Series(np.where(is_case, 1.0, min(w_ext, 1.0)), index=rows.index)


def adversarial_filter(case_rows: pd.DataFrame, ext_rows: pd.DataFrame, max_p_external: float = 0.8,
                       seed: int = 7) -> pd.DataFrame:
    """Оставляет внешние окна, похожие на наши: классификатор «наше или внешнее» не должен быть в них уверен.

    Учим на признаках без источника и компании; внешние строки с P(внешняя) > max_p_external выкидываем.
    Предсказания — по кросс-валидации с разбиением ПО КОМПАНИЯМ: иначе строки одной компании попадают и в
    обучение, и в проверку, классификатор запоминает компании и «уверенно» выкидывает даже похожие.
    """
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold, cross_val_predict

    feats = [c for c in case_rows.columns if c not in NON_FEATURES + ["source", "company", "industry", "target_dow"]]
    x = pd.concat([case_rows[feats], ext_rows[feats]], ignore_index=True)
    y = np.r_[np.zeros(len(case_rows)), np.ones(len(ext_rows))]
    groups = pd.concat([case_rows["source"] + "|" + case_rows["company"],
                        ext_rows["source"] + "|" + ext_rows["company"]], ignore_index=True)
    # Сильно регуляризуем: задача — поймать заметный сдвиг распределения, а не случайные отличия компаний.
    clf = HistGradientBoostingClassifier(max_iter=100, max_depth=3, min_samples_leaf=200, learning_rate=0.05,
                                         l2_regularization=1.0, random_state=seed)
    p_ext = cross_val_predict(clf, x, y, groups=groups, cv=GroupKFold(n_splits=min(5, groups.nunique())),
                              method="predict_proba")[len(case_rows):, 1]
    return ext_rows[p_ext <= max_p_external]


@dataclass(slots=True)
class CatBoostFlowModel:
    params: dict = field(default_factory=lambda: {
        "loss_function": "MultiQuantile:alpha=" + ",".join(map(str, QUANTILES)),
        "iterations": 800, "depth": 6, "learning_rate": 0.05, "random_seed": 7, "verbose": False,
    })
    model: object | None = None

    def fit(self, rows: pd.DataFrame, case_share: float = 0.5) -> CatBoostFlowModel:
        from catboost import CatBoostRegressor, Pool  # опциональная зависимость: uv sync --extra ml

        x, y = rows.drop(columns=NON_FEATURES, errors="ignore"), rows["y"]
        self.model = CatBoostRegressor(**self.params)
        self.model.fit(Pool(x, y, cat_features=CAT_FEATURES, weight=mix_weights(rows, case_share)))
        return self

    def predict(self, rows: pd.DataFrame) -> np.ndarray:
        """Матрица (n, 3): P10, P50, P90 дневного потока."""
        if self.model is None:
            raise RuntimeError("Модель не обучена")
        x = rows.drop(columns=NON_FEATURES, errors="ignore").assign(source="case")   # прогноз всегда «для нас»
        return np.asarray(self.model.predict(x))
