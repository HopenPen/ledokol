"""Прогноз остатка: гибрид трёх слоёв + Монте-Карло.

    остаток(t) = остаток сегодня + Σ [A: известные события] + [B: розничная выручка] + [C: нерегулярный поток]

A — регулярные платежи из истории, налоговый календарь, ручной ввод, счета из 1С (поштучно: EDA показал,
    что 1% крупнейших операций даёт 32% оборота, их нельзя «размазывать» средним);
B — эквайринг/СБП/наличные/маркетплейсы по дням недели (понедельник ×3 из-за зачисления за выходные);
C — всё остальное (B2B без счёта, закупки), средний дневной поток с раздельными приходом и расходом.

Деньги владельца и переводы между своими счетами в прогноз не входят: это реакция на разрыв, а не план.
fit() дорогой и кешируется на версию данных; forecast() дешёвый — новые события и сценарии не требуют
переобучения (инкрементальное обновление, FR-9.3).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.domain.calendar import working_days_after
from app.domain.categories import EXCLUDED_FROM_FORECAST, RETAIL
from app.domain.recurring import RecurringSeries, detect_recurring, project_series
from app.domain.risk import build_headline, detect_gaps
from app.domain.scenarios import Scenario, apply_to_events
from app.domain.taxes import project_taxes
from app.domain.types import Direction, ForecastPoint, ForecastResult, PlannedEvent

MODEL_VERSION = "hybrid-v1"
_WINDOW_WD = 60          # окно оценки уровней, рабочих дней (~3 месяца)
_POOL_WD = 120           # окно для бутстрепа ошибок
_MIN_HISTORY_WD = 20     # меньше — только известные события
_LOW_HISTORY_WD = 60


@dataclass(eq=False, slots=True)
class FittedModel:
    as_of: date
    last_balance: float
    recurring: list[RecurringSeries]
    revenue_dow: np.ndarray            # (7,) ожидаемая розничная выручка по дню недели
    other_in_mean: float               # слой C: средний приход за рабочий день
    other_out_mean: float              # слой C: средний расход за рабочий день
    residual_pool: np.ndarray          # дневные ошибки (факт − модель) для бутстрепа
    client_shares: dict[str, float]    # доля клиента в нерегулярном приходе (для сценария задержки)
    top_clients: list[tuple[str, str, float]]
    history_wd: int
    ops: pd.DataFrame = field(repr=False)
    model_version: str = MODEL_VERSION

    @property
    def low_history(self) -> bool:
        return self.history_wd < _LOW_HISTORY_WD


def fit(ops: pd.DataFrame, panel: pd.DataFrame, as_of: date | None = None) -> FittedModel:
    """ops — категоризированные операции одной компании (после flag_quality), panel — дневной остаток."""
    if as_of is not None:
        cut = pd.Timestamp(as_of)
        ops, panel = ops[ops["operation_date"].le(cut)], panel[panel["date"].le(cut)]
    if panel.empty:
        raise ValueError("Нет истории для прогноза")
    as_of = panel["date"].iloc[-1].date()
    good = ops[ops["quality"].isin(["ok", "after_gap"])]
    recurring = detect_recurring(good, as_of)
    members = {i for s in recurring for i in s.member_index}

    is_retail = good["category"].isin(RETAIL)
    is_other = (~is_retail & ~good["category"].isin(EXCLUDED_FROM_FORECAST | {"tax"})
                & ~good.index.isin(list(members)) & ~_one_offs(good))
    days = pd.DatetimeIndex(panel["date"])
    retail =good[is_retail].groupby("operation_date")["signed"].sum().reindex(days, fill_value=0.0)
    other_in = good[is_other & good["direction"].eq("in")].groupby("operation_date")["amount"].sum() \
        .reindex(days, fill_value=0.0)
    other_out = good[is_other & good["direction"].eq("out")].groupby("operation_date")["amount"].sum() \
        .reindex(days, fill_value=0.0)

    history_wd = len(panel)
    win = slice(-min(_WINDOW_WD, history_wd), None)
    if history_wd < _MIN_HISTORY_WD:
        revenue_dow, oin, oout, pool = np.zeros(7), 0.0, 0.0, np.zeros(1)
    else:
        r_win = retail.iloc[win]
        wd = r_win.index.day_of_week
        overall = _robust_mean(r_win.to_numpy())
        revenue_dow = np.array([_robust_mean(r_win.to_numpy()[wd == k]) if (wd == k).sum() >= 3 else overall
                                for k in range(7)])
        oin, oout = float(other_in.iloc[win].mean()), float(other_out.iloc[win].mean())
        fitted = revenue_dow[retail.index.day_of_week] + oin - oout
        resid = (retail + other_in - other_out).to_numpy() - fitted
        mask = ~panel["after_gap"].to_numpy()
        pool = resid[mask][-_POOL_WD:]
        pool = pool - pool.mean() if len(pool) else np.zeros(1)

    clients = good[is_other & good["category"].eq("client_payment")]
    shares = clients.groupby("cp_key")["amount"].sum()
    shares = (shares / shares.sum()).sort_values(ascending=False) if len(shares) else shares
    names = clients.groupby("cp_key")["counterparty_name"].last()
    top = [(k, str(names[k]), float(v)) for k, v in shares.head(5).items()]

    return FittedModel(
        as_of=as_of, last_balance=float(panel["balance"].iloc[-1]), recurring=recurring, revenue_dow=revenue_dow,
        other_in_mean=oin, other_out_mean=oout, residual_pool=pool, client_shares=shares.to_dict(),
        top_clients=top, history_wd=history_wd, ops=good,
    )


def known_events(m: FittedModel, planned: list[PlannedEvent], horizon_end: date) -> list[PlannedEvent]:
    """Слой A. Ручное событие/счёт заменяет совпадающий регулярный платёж, а не дублирует его (FR-3.4)."""
    projected = [e for s in m.recurring for e in project_series(s, m.as_of, horizon_end)]
    projected += project_taxes(m.ops, m.as_of, horizon_end)
    planned = [e for e in planned if m.as_of < e.event_date <= horizon_end]

    def covered(e: PlannedEvent) -> bool:
        return any(p.direction is e.direction and abs((p.event_date - e.event_date).days) <= 5
                   and abs(p.amount - e.amount) <= 0.2 * e.amount
                   and (p.counterparty_key is None or p.counterparty_key == e.counterparty_key) for p in planned)

    return sorted([e for e in projected if not covered(e)] + planned, key=lambda e: e.event_date)


def forecast(m: FittedModel, planned: list[PlannedEvent] | None = None, *, horizon: int = 30,
             n_sims: int = 1000, seed: int = 7, threshold: float = 0.0, scenario: Scenario | None = None,
             data_warnings: list[str] | None = None) -> ForecastResult:
    days = working_days_after(m.as_of, horizon)
    end = days[-1]
    events = known_events(m, planned or [], end)
    rev_mult, in_mult, out_mult = 1.0, np.ones(horizon), 1.0
    if scenario and not scenario.is_empty:
        events = apply_to_events(scenario, events, m.as_of, end)
        rev_mult = 1 - scenario.revenue_drop_pct / 100
        out_mult = 1 + scenario.fixed_cost_increase_pct / 100
        in_mult = in_mult * rev_mult
        for d in scenario.client_delays:     # нерегулярные оплаты клиента сдвигаются на d.weeks
            share = m.client_shares.get(d.counterparty_key, 0.0)
            in_mult[: d.weeks * 5] -= share * rev_mult

    dow = np.array([d.weekday() for d in days])
    base = m.revenue_dow[dow] * rev_mult + m.other_in_mean * in_mult - m.other_out_mean * out_mult
    rng = np.random.default_rng(seed)
    flows = np.tile(base, (n_sims, 1)) + _block_bootstrap(m.residual_pool, n_sims, horizon, rng)

    idx = {d: i for i, d in enumerate(days)}
    rows = np.arange(n_sims)
    for e in events:
        pos = idx.get(e.event_date)
        if pos is None:
            continue
        hit = rng.random(n_sims) < e.probability
        shift = rng.integers(-e.date_jitter_days, e.date_jitter_days + 1, n_sims) if e.date_jitter_days else 0
        cols = np.clip(pos + shift, 0, horizon - 1)
        np.add.at(flows, (rows[hit], np.broadcast_to(cols, n_sims)[hit]), e.signed)

    paths = m.last_balance + np.cumsum(flows, axis=1)
    q10, q50, q90 = np.quantile(paths, [0.1, 0.5, 0.9], axis=0)
    below = (paths < threshold).mean(axis=0)
    points = [ForecastPoint(d, float(a), float(b), float(c), float(p))
              for d, a, b, c, p in zip(days, q10, q50, q90, below)]
    alerts = detect_gaps(days, paths, events, threshold)
    return ForecastResult(
        as_of=m.as_of, last_balance=m.last_balance, threshold=threshold, points=points, events=events,
        alerts=alerts, headline=build_headline(points, alerts, threshold), data_warnings=data_warnings or [],
        low_history=m.low_history,
    )


# --- бейзлайны для честного сравнения подходов (раздел 6 ТЗ) -------------------------------------------------

def naive_forecast(m: FittedModel, horizon: int = 30) -> np.ndarray:
    """Остаток не меняется."""
    return np.full(horizon, m.last_balance)


def mean_flow_forecast(ops: pd.DataFrame, panel: pd.DataFrame, horizon: int = 30) -> np.ndarray:
    """Средний дневной чистый поток за последние 60 рабочих дней (без денег владельца)."""
    tail = panel.tail(_WINDOW_WD)
    own = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["operation_date"].isin(tail["date"])]
    mean_net = (tail["net"].sum() - own["signed"].sum()) / max(len(tail), 1)
    return float(panel["balance"].iloc[-1]) + mean_net * np.arange(1, horizon + 1)


# --- helpers -----------------------------------------------------------------------------------------------

def _robust_mean(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    lo, hi = np.quantile(x, [0.05, 0.95])
    return float(np.clip(x, lo, hi).mean())


def _one_offs(ops: pd.DataFrame) -> pd.Series:
    """Разовые крупные операции (>20× медианы и > p99,9 по направлению) не учат статистический слой."""
    grp = ops.groupby("direction")["amount"]
    return (ops["amount"] > 20 * grp.transform("median")) & (ops["amount"] > grp.transform(lambda s: s.quantile(0.999)))


def _block_bootstrap(pool: np.ndarray, n: int, h: int, rng: np.random.Generator, block: int = 5) -> np.ndarray:
    """Блочный бутстреп: сохраняет локальную автокорреляцию потока (неделя «хорошая» / «плохая»)."""
    if len(pool) <= block:
        return rng.choice(pool, size=(n, h), replace=True)
    n_blocks = -(-h // block)
    starts = rng.integers(0, len(pool) - block + 1, size=(n, n_blocks))
    idx = (starts[..., None] + np.arange(block)).reshape(n, -1)[:, :h]
    return pool[idx]


__all__ = ["FittedModel", "fit", "forecast", "known_events", "naive_forecast", "mean_flow_forecast", "Direction"]
