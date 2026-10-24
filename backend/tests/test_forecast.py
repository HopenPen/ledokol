"""Инварианты прогноза. Проверяем свойства, которые должны выполняться всегда, а не конкретные числа."""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from app.domain.forecast import fit, forecast
from app.domain.pipeline import prepare_company
from app.domain.recurring import detect_recurring
from app.domain.scenarios import ExtraExpense, Scenario
from app.domain.types import Direction, EventSource, PlannedEvent
from tests.conftest import make_company


@pytest.fixture(scope="module")
def model():
    prep = prepare_company(make_company())
    return fit(prep.ops, prep.panel)


def test_rent_and_salary_detected_as_recurring(model):
    cats = {s.category for s in model.recurring}
    assert "rent" in cats and "salary" in cats


def test_quantiles_are_ordered(model):
    res = forecast(model, n_sims=300)
    assert all(p.p10 <= p.p50 <= p.p90 for p in res.points)
    assert len(res.points) == 30


def test_empty_scenario_equals_base(model):
    base = forecast(model, n_sims=300, seed=3)
    same = forecast(model, n_sims=300, seed=3, scenario=Scenario())
    assert [p.p50 for p in base.points] == [p.p50 for p in same.points]


def test_extra_expense_lowers_balance_after_its_date(model):
    base = forecast(model, n_sims=300, seed=3)
    day = base.points[10].day
    neg = forecast(model, n_sims=300, seed=3, scenario=Scenario(extra_expenses=(ExtraExpense(day, 1_000_000),)))
    assert np.allclose([p.p50 for p in neg.points[:10]], [p.p50 for p in base.points[:10]])
    assert neg.points[15].p50 < base.points[15].p50 - 900_000


def test_manual_inflow_raises_forecast(model):
    """Сценарий жюри: «ввели новое событие — смотрим реакцию». Прогноз должен сдвинуться на сумму события."""
    base = forecast(model, n_sims=300, seed=3)
    ev = PlannedEvent(base.points[5].day, 500_000, Direction.IN, "Клиент обещал", "client_payment", EventSource.MANUAL)
    after = forecast(model, [ev], n_sims=300, seed=3)
    assert after.points[-1].p50 - base.points[-1].p50 == pytest.approx(500_000, rel=0.05)


def test_big_outflow_produces_gap_alert(model):
    day = model.as_of + timedelta(days=10)
    hit = forecast(model, n_sims=300, scenario=Scenario(extra_expenses=(ExtraExpense(day, model.last_balance * 3),)))
    assert hit.alerts, "огромный расход должен дать предупреждение"
    a = hit.alerts[0]
    assert a.probability >= 0.8 and a.shortfall > 0 and a.actions
    assert "не хватит" in hit.headline


def test_short_history_still_forecasts():
    prep = prepare_company(make_company(days=20))
    res = forecast(fit(prep.ops, prep.panel), n_sims=100)
    assert res.low_history and len(res.points) == 30


def test_stopped_series_is_not_projected():
    ops = make_company(days=240)
    prep = prepare_company(ops[~((ops["counterparty_name"] == "ООО «Арендодатель»")
                                 & (ops["operation_date"] > ops["operation_date"].min() + timedelta(days=150)))])
    as_of = prep.panel["date"].iloc[-1].date()
    assert "rent" not in {s.category for s in detect_recurring(prep.ops, as_of)}
