"""Признаки для ML-классификатора кассового разрыва (TabPFN): «будет ли остаток ниже нуля в ближайшие h дней».

Это тот же набор и тот же порядок признаков, на которых модель проверялась в analytics/experiments/gap_classifier_v2.py.
Менять формулы здесь нельзя без переобучения: модель обучена на этих значениях. Чтобы порядок и смысл не разошлись,
есть тест, который сверяет признаки с выборкой эксперимента на реальных данных (tests/test_ml_risk.py).

Будущего функция не видит: все ряды обрезаются по дате прогноза t.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.domain.categories import EXCLUDED_FROM_FORECAST
from app.domain.ml_flow import operational_flow, scale_of
from app.domain.pipeline import PreparedCompany
from app.domain.types import Direction, ForecastResult

HORIZONS = (5, 10, 20, 30)
YEAR_WD = 252                                    # рабочих дней в году (признак «то же окно год назад»)
HORIZON_DAYS = 30                                # прогноз гибрида считается на 30 дней, окна короче берутся из него

# Порядок важен: TabPFN получает признаки по позициям, первый столбец — категориальный (отрасль).
FEATURES = [
    "industry_code", "h", "cushion", "min_bal_60", "bal_trend_20", "inj_events_180", "inj_amount_180", "mean_5", "mean_20",
    "mean_60", "std_20", "share_pos_20", "lag_year", "known_out", "known_in", "cushion_after_out", "cushion_after_net",
    "hyb_pmax", "hyb_pmean", "hyb_first_day", "hyb_min_p10", "hyb_min_p50", "hyb_end_p50",
]


@dataclass(slots=True)
class GapContext:
    """Ряды компании по рабочим дням, нужные для признаков."""

    days: pd.DatetimeIndex
    bal: np.ndarray        # остаток на конец дня
    flow: np.ndarray       # поток без денег владельца, переводов и кредитов
    inj: np.ndarray        # деньги, которые владелец довнёс в этот день
    cum: np.ndarray        # накопленный поток (с нулём в начале)
    cuminj: np.ndarray     # накопленное число дней с довнесением (с нулём в начале)


def build_context(prep: PreparedCompany) -> GapContext:
    ops, panel = prep.ops, prep.panel.reset_index(drop=True)
    owner_in = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["direction"].eq("in")].groupby("operation_date")["amount"].sum()
    inj = panel["date"].map(owner_in).fillna(0.0).to_numpy(dtype=float)
    flow = operational_flow(prep).to_numpy(dtype=float)
    return GapContext(days=pd.DatetimeIndex(panel["date"]), bal=panel["balance"].to_numpy(dtype=float), flow=flow, inj=inj,
                      cum=np.r_[0.0, np.cumsum(flow)], cuminj=np.r_[0.0, np.cumsum(inj > 0)])


def _event_curves(result: ForecastResult) -> tuple[np.ndarray, np.ndarray]:
    """Накопленные по дням суммы ожидаемых платежей: обязательные списания и ожидаемые поступления (с учётом вероятности)."""
    day_idx = {p.day: i for i, p in enumerate(result.points)}
    out_cum, in_cum = np.zeros(HORIZON_DAYS), np.zeros(HORIZON_DAYS)
    for e in result.events:
        i = day_idx.get(e.event_date)
        if i is None:
            continue
        if e.direction is Direction.OUT:
            out_cum[i:] += e.amount
        else:
            in_cum[i:] += e.amount * e.probability
    return out_cum, in_cum


def gap_features(ctx: GapContext, result: ForecastResult, industry_code: float, t: int | None = None,
                 horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """Строки признаков (по одной на горизонт) для даты прогноза t (по умолчанию — последний день выписки).

    result — прогноз гибрида от той же даты: 30 дней, 150 симуляций, зерно 7, без порога (так он считался при обучении).
    industry_code — код отрасли из meta.json модели или NaN, если отрасль неизвестна.
    """
    t = len(ctx.bal) - 1 if t is None else t
    if len(result.points) < HORIZON_DAYS:
        raise ValueError("нужен прогноз гибрида на 30 дней")
    sc = scale_of(ctx.flow[max(0, t - 59): t + 1])
    h_n = ctx.flow[: t + 1] / sc
    p10 = np.array([p.p10 for p in result.points])
    p50 = np.array([p.p50 for p in result.points])
    prob = np.array([p.prob_below for p in result.points])
    out_cum, in_cum = _event_curves(result)
    bal0 = ctx.bal[t]
    cushion = bal0 / sc
    rows = []
    for h in horizons:
        out_h, in_h = out_cum[h - 1] / sc, in_cum[h - 1] / sc
        lag_year = (ctx.cum[t - YEAR_WD + h + 1] - ctx.cum[t - YEAR_WD + 1]) / sc if t - YEAR_WD >= 0 else np.nan
        pr = prob[:h]
        rows.append({
            "industry_code": industry_code, "h": h, "cushion": cushion,
            "min_bal_60": ctx.bal[max(0, t - 59): t + 1].min() / sc, "bal_trend_20": (bal0 - ctx.bal[max(0, t - 20)]) / sc,
            "inj_events_180": float(ctx.cuminj[t + 1] - ctx.cuminj[max(0, t - 179)]),
            "inj_amount_180": ctx.inj[max(0, t - 179): t + 1].sum() / sc,
            "mean_5": h_n[-5:].mean(), "mean_20": h_n[-20:].mean(), "mean_60": h_n[-60:].mean(), "std_20": h_n[-20:].std(),
            "share_pos_20": (h_n[-20:] > 0).mean(), "lag_year": lag_year,
            "known_out": out_h, "known_in": in_h, "cushion_after_out": cushion - out_h, "cushion_after_net": cushion - out_h + in_h,
            "hyb_pmax": pr.max(), "hyb_pmean": pr.mean(), "hyb_first_day": int(np.argmax(pr >= 0.2)) + 1 if (pr >= 0.2).any() else h + 1,
            "hyb_min_p10": p10[:h].min() / sc, "hyb_min_p50": p50[:h].min() / sc, "hyb_end_p50": (p50[h - 1] - bal0) / sc,
        })
    return pd.DataFrame(rows)[FEATURES]
