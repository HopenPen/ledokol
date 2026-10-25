"""Rolling-origin бэктест (раздел 6 ТЗ): несколько отсечек на компанию, горизонт 30 рабочих дней.

Модель видит только данные до отсечки. Окна с «дырами» в выписке не оцениваются. Сравниваем гибрид с двумя
бейзлайнами, а разрывы оцениваем отдельно: recall, precision, заблаговременность.

Отложенные компании (holdout) не участвуют в подборе правил — это имитация контрольного датасета жюри.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.domain.categories import EXCLUDED_FROM_FORECAST
from app.domain.forecast import fit, forecast, mean_flow_forecast, naive_forecast
from app.domain.pipeline import PreparedCompany

HORIZONS = (5, 10, 20, 30)
# Порог, с которого считаем, что «предупреждение выдано». 0,5 был взят с потолка; вложенная кросс-валидация по
# компаниям (analytics/model_evaluation.ipynb) выбирает для гибрида 0,20–0,25 в разных фолдах. Пропустить разрыв
# дороже, чем лишний раз предупредить. В приложении эпизоды показываются с ALERT_MIN_PROB = 0,2 (domain/risk.py).
GAP_PROB = 0.25


@dataclass(slots=True)
class BacktestConfig:
    horizon: int = 30
    n_cutoffs: int = 6
    step_wd: int = 10
    min_history_wd: int = 60
    n_sims: int = 300
    seed: int = 7


def backtest_company(prep: PreparedCompany, cfg: BacktestConfig = BacktestConfig()) -> list[dict]:
    panel, ops = prep.panel.reset_index(drop=True), prep.ops
    n, h = len(panel), cfg.horizon
    rows: list[dict] = []
    for k in range(cfg.n_cutoffs):
        pos = n - 1 - h - k * cfg.step_wd
        if pos < cfg.min_history_wd:
            break
        window = panel.iloc[pos + 1: pos + 1 + h]
        if window["after_gap"].any() or len(window) < h:
            continue
        cutoff = panel.loc[pos, "date"]
        hist_ops, hist_panel = ops[ops["operation_date"].le(cutoff)], panel.iloc[: pos + 1]
        m = fit(hist_ops, hist_panel)
        res = forecast(m, [], horizon=h, n_sims=cfg.n_sims, seed=cfg.seed)
        p10 = np.array([p.p10 for p in res.points])
        p50 = np.array([p.p50 for p in res.points])
        p90 = np.array([p.p90 for p in res.points])
        actual = window["balance"].to_numpy()
        # Прогноз сознательно не включает деньги владельца и переводы между своими счетами (это реакция на
        # разрыв, а не план). Поэтому сравниваем ещё и с «операционным» остатком: факт минус эти потоки.
        excl = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["quality"].ne("duplicate")] \
            .groupby("operation_date")["signed"].sum()
        actual_oper = actual - np.cumsum(window["date"].map(excl).fillna(0.0).to_numpy())
        naive = naive_forecast(m, h)
        meanf = mean_flow_forecast(hist_ops, hist_panel, h)
        out_flow = hist_ops[hist_ops["direction"].eq("out") & hist_ops["operation_date"].isin(hist_panel["date"].tail(60))]
        scale = max(out_flow["amount"].sum() / 60, 1.0)

        gap_days = _actual_gap_days(window, ops)
        ongoing = panel.loc[pos, "balance"] < 0
        pred_alert = next((a for a in res.alerts if a.probability >= GAP_PROB), None)
        row = {
            "company_id": prep.company_id, "cutoff": cutoff.date(), "scale": scale, "ongoing_gap": bool(ongoing),
            "coverage": float(((actual >= p10) & (actual <= p90)).mean()),
            "gap_actual": bool(gap_days.size), "gap_pred": pred_alert is not None,
            # Непрерывная оценка риска на окно — максимум по дням доли траекторий ниже порога. Нужна для ROC/PR:
            # gap_pred — это та же оценка, срезанная по порогу GAP_PROB.
            "gap_score": max(p.prob_below for p in res.points),
            "lead_wd": int(gap_days[0]) + 1 if gap_days.size else None,
            "pred_start_wd": res.points.index(next(p for p in res.points if p.day == pred_alert.start)) + 1
            if pred_alert else None,
        }
        for hz in HORIZONS:
            row[f"err_model_h{hz}"] = (p50[hz - 1] - actual[hz - 1]) / scale   # со знаком — для смещения
            row[f"mae_model_h{hz}"] = abs(p50[hz - 1] - actual[hz - 1]) / scale
            row[f"mae_naive_h{hz}"] = abs(naive[hz - 1] - actual[hz - 1]) / scale
            row[f"mae_mean_h{hz}"] = abs(meanf[hz - 1] - actual[hz - 1]) / scale
            row[f"mae_oper_model_h{hz}"] = abs(p50[hz - 1] - actual_oper[hz - 1]) / scale
            row[f"mae_oper_naive_h{hz}"] = abs(naive[hz - 1] - actual_oper[hz - 1]) / scale
        row["coverage_oper"] = float(((actual_oper >= p10) & (actual_oper <= p90)).mean())
        rows.append(row)
    return rows


def _actual_gap_days(window: pd.DataFrame, ops: pd.DataFrame) -> np.ndarray:
    """Явный разрыв (остаток < 0) или скрытый: без денег владельца в этот день остаток был бы < 0."""
    owner = ops[ops["category"].isin(EXCLUDED_FROM_FORECAST) & ops["direction"].eq("in")] \
        .groupby("operation_date")["amount"].sum()
    inj = window["date"].map(owner).fillna(0.0).to_numpy()
    bal = window["balance"].to_numpy()
    return np.flatnonzero((bal < 0) | ((inj > 0) & (bal - inj < 0)))


def summarize(rows: pd.DataFrame) -> dict:
    if rows.empty:
        return {"windows": 0}
    out: dict = {"windows": int(len(rows)), "companies": int(rows["company_id"].nunique())}
    for hz in HORIZONS:
        model, naive, mean = (rows[f"mae_{k}_h{hz}"].mean() for k in ("model", "naive", "mean"))
        om, on = rows[f"mae_oper_model_h{hz}"].mean(), rows[f"mae_oper_naive_h{hz}"].mean()
        out[f"h{hz}"] = {"mae_model": round(model, 3), "mae_naive": round(naive, 3), "mae_mean": round(mean, 3),
                         "mase_vs_naive": round(model / naive, 3) if naive else None,
                         "oper_mase_vs_naive": round(om / on, 3) if on else None}
    out["coverage_p10_p90"] = round(rows["coverage"].mean(), 3)
    out["coverage_p10_p90_oper"] = round(rows["coverage_oper"].mean(), 3)
    g = rows[~rows["ongoing_gap"]]
    tp = int((g["gap_pred"] & g["gap_actual"]).sum())
    fp = int((g["gap_pred"] & ~g["gap_actual"]).sum())
    fn = int((~g["gap_pred"] & g["gap_actual"]).sum())
    out["gaps"] = {
        "windows_with_gap": int(g["gap_actual"].sum()), "tp": tp, "fp": fp, "fn": fn,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "median_lead_wd": float(g.loc[g["gap_pred"] & g["gap_actual"], "lead_wd"].median()) if tp else None,
    }
    return out


def split_holdout(company_ids: list[str], frac: float = 0.2, seed: int = 42) -> set[str]:
    rng = np.random.default_rng(seed)
    k = max(1, int(round(len(company_ids) * frac)))
    return set(rng.choice(sorted(company_ids), size=k, replace=False).tolist())
