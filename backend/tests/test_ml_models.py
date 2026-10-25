"""Сравнение моделей: гибрид, CatBoost, ансамбль; TabPFN без пакета отвечает «недоступно», а не ошибкой."""
from __future__ import annotations

import pytest

from app.core.config import get_settings
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login

pytestmark = pytest.mark.skipif(not (get_settings().ml_flow_dir and __import__("pathlib").Path(get_settings().ml_flow_dir, "mean.cbm").exists()),
                                reason="нет файлов модели CatBoost")


def test_models_endpoint_returns_all_models(client, monkeypatch, tmp_path):
    h = _login(client, "alice")
    cid = _import(client, h, to_case_csv(make_company(days=330)))["company"]["id"]
    r = client.get(f"/api/companies/{cid}/models", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [m["key"] for m in body["models"]] == ["hybrid", "catboost", "ensemble"]
    for m in body["models"]:
        assert m["available"] and 0 <= m["probability"] <= 1 and len(m["points"]) == 30
        assert all(p["p10"] <= p["p50"] <= p["p90"] for p in m["points"])
    hyb, cb, ens = (m["probability"] for m in body["models"])
    assert ens == pytest.approx((hyb + cb) / 2, abs=1e-3)


def test_models_endpoint_is_closed_for_anonymous(client):
    assert client.get("/api/companies/x/models").status_code == 401


def test_dev_no_auth_gives_access_without_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_no_auth", True)
    assert client.get("/api/companies").status_code == 200
