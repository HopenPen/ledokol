"""Текущая нехватка денег не должна описываться как будущий риск."""
import json
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from app.domain.types import ForecastResult
from app.llm.privacy import build_context
from tests.test_api import _login
from tests.test_import_acceptance import row, statement


@pytest.fixture
def negative_balance(client):
    headers = _login(client, "alice")
    imported = client.post("/api/companies/import", headers=headers,
                           files={"file": ("single.csv", statement([row()]), "text/csv")})
    assert imported.status_code == 201
    return client, headers, imported.json()[0]["company"]["id"]


def test_negative_balance_is_already_a_shortfall_with_no_recovery(negative_balance):
    client, headers, cid = negative_balance
    result = client.get(f"/api/companies/{cid}/forecast", headers=headers).json()
    assert "денег уже не хватает" in result["headline"]
    assert "23 октября" in result["headline"]  # дата выписки, а не выдуманное «сегодня»
    assert "не достигает нуля" in result["headline"]
    assert result["last_balance"] == -125.5


def test_recovery_date_is_shown_and_preview_matches_saved(negative_balance):
    client, headers, cid = negative_balance
    event = {"event_date": "2026-10-28", "amount": "1000000", "direction": "in",
             "title": "Ожидаемое поступление", "confidence": "certain"}
    preview = client.post(f"/api/companies/{cid}/forecast/preview", headers=headers,
                          json={"extra_events": [event]}).json()
    assert "денег уже не хватает" in preview["headline"]
    assert "впервые достигнет нуля 28 октября" in preview["headline"]
    assert client.post(f"/api/companies/{cid}/events", headers=headers, json=event).status_code == 201
    saved = client.get(f"/api/companies/{cid}/forecast", headers=headers).json()
    assert preview == saved


def test_positive_balance_below_reserve_uses_reserve_wording(client):
    headers = _login(client, "alice")
    response = client.post("/api/companies/import", headers=headers,
                           files={"file": ("positive.csv", statement([row(balance_eod="1000")]), "text/csv")})
    cid = response.json()[0]["company"]["id"]
    assert client.patch(f"/api/companies/{cid}", headers=headers, json={"min_balance": "2000"}).status_code == 200
    result = client.get(f"/api/companies/{cid}/dashboard", headers=headers).json()["forecast"]
    assert "ниже установленного минимума" in result["headline"]
    assert "денег уже не хватает" not in result["headline"]


def test_small_current_shortfall_does_not_round_to_zero(client):
    headers = _login(client, "alice")
    response = client.post("/api/companies/import", headers=headers,
                           files={"file": ("kopeck.csv", statement([row(balance_eod="-0.01")]), "text/csv")})
    cid = response.json()[0]["company"]["id"]
    result = client.get(f"/api/companies/{cid}/forecast", headers=headers).json()
    assert "денег уже не хватает: 0,01 ₽" in result["headline"]


def test_current_balance_headline_does_not_leak_precise_amount_to_llm():
    result = ForecastResult(as_of=date(2026, 10, 23), last_balance=-125.5, threshold=0,
                            points=[], events=[], alerts=[], headline="Денег уже не хватает: 125,50 ₽")
    context = json.loads(build_context(result))
    assert context["balance_now"] == 0
    assert "125,50" not in context["headline"]
    assert context["first_recovery_date"] is None


def test_llm_context_serializes_numpy_alert_flag():
    day = date(2026, 10, 23)
    alert = SimpleNamespace(start=day, end=day, probability=0.6, shortfall=2500,
                            worst_case=np.bool_(True), causes=[], actions=[])
    result = ForecastResult(as_of=day, last_balance=1000, threshold=0, points=[], events=[],
                            alerts=[alert], headline="Возможна нехватка")
    context = json.loads(build_context(result))
    assert context["gaps"][0]["only_in_bad_case"] is True
