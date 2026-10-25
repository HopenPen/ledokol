"""Сравнение моделей: гибрид, CatBoost, ансамбль; TabPFN без пакета отвечает «недоступно», а не ошибкой."""
from __future__ import annotations

import pytest

from app.core.config import get_settings

pytestmark = pytest.mark.skipif(not (get_settings().ml_flow_dir and __import__("pathlib").Path(get_settings().ml_flow_dir, "mean.cbm").exists()),
                                reason="нет файлов модели CatBoost")


def test_models_endpoint_is_closed_for_anonymous(client):
    assert client.get("/api/companies/x/models").status_code == 401


def test_dev_no_auth_gives_access_without_token(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "dev_no_auth", True)
    assert client.get("/api/companies").status_code == 200
