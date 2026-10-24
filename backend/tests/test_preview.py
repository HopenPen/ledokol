"""Черновик должен показывать тот же результат, что и сохранённое событие."""
from __future__ import annotations

import pytest

from app.db.models import ForecastRun
from app.db.session import SessionLocal
from tests.test_api import _login
from tests.test_planfact import staged  # noqa: F401


@pytest.mark.parametrize("kind,confidence,direction", [
    ("manual", "certain", "in"),
    ("invoice_out", "likely", "in"),
    ("invoice_in", "unsure", "out"),
    ("tax", "certain", "out"),
])
def test_preview_matches_saved_event(staged, kind, confidence, direction):
    c, headers, cid, _ = staged
    base = c.get(f"/api/companies/{cid}/dashboard", headers=headers).json()["forecast"]
    event = {"event_date": base["points"][5]["date"], "amount": "345678.90", "direction": direction,
             "title": "Проверяем до сохранения", "kind": kind, "confidence": confidence,
             "counterparty_key": "0055555555"}

    response = c.post(f"/api/companies/{cid}/forecast/preview", headers=headers, json={"extra_events": [event]})
    assert response.status_code == 200
    preview = response.json()
    assert c.get(f"/api/companies/{cid}/events", headers=headers).json() == []
    with SessionLocal() as session:
        assert session.query(ForecastRun).count() == 1  # черновик не создаёт официальный снимок
    assert c.get(f"/api/companies/{cid}/dashboard", headers=headers).json()["forecast"] == base

    saved = c.post(f"/api/companies/{cid}/events", headers={**headers, "Idempotency-Key": "preview-save"},
                   json=event)
    assert saved.status_code == 201
    actual = c.get(f"/api/companies/{cid}/dashboard", headers=headers).json()["forecast"]
    assert preview == actual


def test_preview_requires_company_ownership(staged):
    c, _, cid, _ = staged
    bob = _login(c, "bob")
    assert c.post(f"/api/companies/{cid}/forecast/preview", headers=bob, json={}).status_code == 404
    assert c.post(f"/api/companies/{cid}/forecast/preview", json={}).status_code == 401


@pytest.mark.parametrize("horizon", [60, 90])
def test_preview_uses_selected_horizon(staged, horizon):
    c, headers, cid, _ = staged
    base = c.get(f"/api/companies/{cid}/forecast?horizon={horizon}", headers=headers).json()
    event = {"event_date": base["points"][44]["date"], "amount": "500000", "direction": "in",
             "title": "Оплата за пределами первого месяца", "confidence": "certain"}
    response = c.post(f"/api/companies/{cid}/forecast/preview", headers=headers,
                      json={"extra_events": [event], "horizon": horizon})
    assert response.status_code == 200
    assert len(response.json()["points"]) == horizon
    c.post(f"/api/companies/{cid}/events", headers=headers, json=event)
    saved = c.get(f"/api/companies/{cid}/forecast?horizon={horizon}", headers=headers).json()
    assert response.json() == saved


@pytest.mark.parametrize("horizon", [0, 91])
def test_preview_rejects_unsupported_horizon(staged, horizon):
    c, headers, cid, _ = staged
    assert c.post(f"/api/companies/{cid}/forecast/preview", headers=headers,
                  json={"horizon": horizon}).status_code == 422


def test_preview_rejects_invalid_event_without_saving(staged):
    c, headers, cid, _ = staged
    response = c.post(f"/api/companies/{cid}/forecast/preview", headers=headers, json={
        "extra_events": [{"event_date": "2026-11-01", "amount": "0", "direction": "in", "title": "Ошибка",
                          "owner_id": "someone-else"}],
    })
    assert response.status_code == 422
    assert c.get(f"/api/companies/{cid}/events", headers=headers).json() == []
