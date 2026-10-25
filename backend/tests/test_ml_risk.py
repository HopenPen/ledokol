"""ML-оценка риска разрыва (TabPFN): признаки, отсутствие утечки будущего, эндпоинт и сверка с выборкой эксперимента."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.domain.forecast import fit, forecast
from app.domain.gap_features import FEATURES, HORIZONS, GapContext, build_context, gap_features
from app.domain.pipeline import prepare_company
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login


def _forecast_at(prep, t: int):
    """Прогноз гибрида от даты t, как при обучении: 30 дней, 150 симуляций, зерно 7, без событий пользователя."""
    panel = prep.panel.reset_index(drop=True)
    cutoff = panel.loc[t, "date"]
    m = fit(prep.ops[prep.ops["operation_date"].le(cutoff)], panel.iloc[: t + 1])
    return forecast(m, [], horizon=30, n_sims=150, seed=7)


@pytest.fixture(scope="module")
def prep():
    return prepare_company(make_company(days=330))


def test_features_have_training_columns_and_sane_values(prep):
    ctx = build_context(prep)
    t = len(ctx.bal) - 1
    f = gap_features(ctx, _forecast_at(prep, t), industry_code=3.0)
    assert list(f.columns) == FEATURES and f["h"].tolist() == list(HORIZONS)
    # чем длиннее горизонт, тем больше известных платежей и не меньше максимальный риск
    assert f["known_out"].is_monotonic_increasing and f["hyb_pmax"].is_monotonic_increasing
    # запас = остаток в дневных оборотах; после обязательных платежей он не больше исходного
    assert (f["cushion_after_out"] <= f["cushion"] + 1e-9).all()
    assert (f["hyb_first_day"] >= 1).all() and f["cushion"].nunique() == 1


def test_features_do_not_look_into_the_future(prep):
    ctx = build_context(prep)
    t = len(ctx.bal) - 40
    result = _forecast_at(prep, t)
    clean = gap_features(ctx, result, industry_code=1.0, t=t)
    poisoned = GapContext(days=ctx.days, bal=ctx.bal.copy(), flow=ctx.flow.copy(), inj=ctx.inj.copy(), cum=ctx.cum.copy(),
                          cuminj=ctx.cuminj.copy())
    poisoned.bal[t + 1:], poisoned.flow[t + 1:], poisoned.inj[t + 1:] = 1e12, 1e12, 1e12
    poisoned.cum[t + 2:], poisoned.cuminj[t + 2:] = 1e12, 1e12
    pd.testing.assert_frame_equal(clean, gap_features(poisoned, result, industry_code=1.0, t=t))


def test_unknown_industry_is_a_missing_value_not_a_crash(prep):
    f = gap_features(build_context(prep), _forecast_at(prep, len(prep.panel) - 1), industry_code=float("nan"))
    assert f["industry_code"].isna().all()
    assert f[["cushion", "known_out", "hyb_pmax", "mean_60"]].notna().all(axis=None)


class _FakePredictor:
    meta = {"industries": ["Розница"], "cv": {"30": {"precision": 0.63}},
            "thresholds": {str(h): {"balanced": 0.3, "high_recall": 0.1} for h in HORIZONS}}
    device = "cpu"

    def industry_code(self, industry):
        return float("nan")

    def predict(self, features):
        return np.array([0.05, 0.2, 0.4, 0.9])[: len(features)]


def test_ml_risk_endpoint_without_model_says_unavailable(client, monkeypatch, tmp_path):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "ml_gap_dir", str(tmp_path / "нет-модели"))   # независимо от того, обучена ли модель на машине
    h = _login(client, "alice")
    cid = _import(client, h, to_case_csv(make_company()))["company"]["id"]
    r = client.get(f"/api/companies/{cid}/ml-risk", headers=h)
    assert r.status_code == 200 and r.json()["available"] is False and "ML-модель" in r.json()["reason"]


def test_ml_risk_endpoint_returns_horizons(client, monkeypatch):
    import app.services.ml_risk as svc
    monkeypatch.setattr(svc, "get_predictor", lambda: _FakePredictor())
    h = _login(client, "alice")
    cid = _import(client, h, to_case_csv(make_company(days=330)))["company"]["id"]
    body = client.get(f"/api/companies/{cid}/ml-risk", headers=h).json()
    assert body["available"] and body["state"] == "ok" and [x["days"] for x in body["horizons"]] == list(HORIZONS)
    assert [x["alert"] for x in body["horizons"]] == [False, False, True, True]          # порог «баланс» 0,3
    assert [x["alert_high_recall"] for x in body["horizons"]] == [False, True, True, True]  # порог «80% разрывов» 0,1


def test_ml_risk_is_closed_for_foreign_company_and_anonymous(client):
    alice, bob = _login(client, "alice"), _login(client, "bob")
    cid = _import(client, alice, to_case_csv(make_company()))["company"]["id"]
    assert client.get(f"/api/companies/{cid}/ml-risk", headers=bob).status_code == 404
    assert client.get(f"/api/companies/{cid}/ml-risk").status_code == 401


DATASET = Path(os.environ.get("GAP_DATASET", "../analytics/experiments/out/gap_v2_dataset.csv"))


@pytest.mark.skipif(not (os.environ.get("CASE_DIR") and DATASET.exists()), reason="нужны данные кейса (CASE_DIR) и выборка эксперимента")
def test_features_match_the_experiment_dataset_on_real_data():
    """Признаки приложения должны совпадать со значениями, на которых обучалась модель (проверка на реальных компаниях)."""
    from app.domain.ingest import read_statement
    from app.domain.pipeline import split_by_company

    ds = pd.read_csv(DATASET)
    industries = sorted(ds["industry"].dropna().unique().tolist())
    ds["industry_code"] = ds["industry"].map({n: i for i, n in enumerate(industries)})
    raw = read_statement(open(os.path.join(os.environ["CASE_DIR"], "all_operations.csv"), "rb").read())
    by_company = split_by_company(raw)
    checked = 0
    for cid in ("C009", "C066", "C117"):
        prep = prepare_company(by_company[cid])
        ctx = build_context(prep)
        for _, row in ds[(ds["company"] == cid) & (ds["is_eval"] == 1) & (ds["h"] == 30)].head(3).iterrows():
            t = int(row["t"])
            got = gap_features(ctx, _forecast_at(prep, t), industry_code=row["industry_code"], t=t)
            got = got[got["h"] == 30].iloc[0]
            for col in FEATURES:
                assert np.isclose(got[col], row[col], rtol=1e-3, atol=1e-3, equal_nan=True), (cid, t, col, got[col], row[col])
            checked += 1
    assert checked >= 6
