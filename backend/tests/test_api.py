"""Интеграционные тесты API на настоящей SQLite (без моков ORM): авторизация, владение, идемпотентность."""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.logging import RedactingFilter, redact
from app.integrations.http import IntegrationError, ResilientClient
from tests.conftest import make_company, to_case_csv


def _login(c: TestClient, login: str) -> dict:
    r = c.post("/api/auth/login", json={"login": login, "password": f"pw-{login}"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _import(c: TestClient, headers: dict, csv: bytes) -> dict:
    r = c.post("/api/companies/import", headers=headers, files={"file": ("s.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()[0]


def test_requires_auth(client):
    assert client.get("/api/companies").status_code == 401


def test_wrong_password_and_unknown_user_look_the_same(client):
    a = client.post("/api/auth/login", json={"login": "alice", "password": "nope"})
    b = client.post("/api/auth/login", json={"login": "nobody", "password": "nope"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_import_then_dashboard(client):
    h = _login(client, "alice")
    res = _import(client, h, to_case_csv(make_company()))
    dash = client.get(f"/api/companies/{res['company']['id']}/dashboard", headers=h)
    assert dash.status_code == 200
    body = dash.json()
    assert len(body["forecast"]["points"]) == 30 and body["forecast"]["headline"]
    assert {e["source"] for e in body["forecast"]["events"]} >= {"history", "calendar"}


def test_reimport_same_file_is_noop(client):
    h = _login(client, "alice")
    csv = to_case_csv(make_company())
    first = _import(client, h, csv)
    second = _import(client, h, csv)
    assert first["rows_new"] > 0 and second["rows_new"] == 0 and second["already_imported"]


def test_incremental_upload_adds_only_new_rows(client):
    h = _login(client, "alice")
    full = make_company(days=240)
    cut = full["operation_date"].min() + timedelta(days=200)
    first = _import(client, h, to_case_csv(full[full["operation_date"] <= cut]))
    cid = first["company"]["id"]
    r = client.post(f"/api/companies/{cid}/statements", headers=h,
                    files={"file": ("s.csv", to_case_csv(full), "text/csv")})   # весь файл, включая старое
    assert r.json()[0]["rows_new"] == len(full) - first["rows_new"]


def test_foreign_company_is_404_not_403(client):
    alice, bob = _login(client, "alice"), _login(client, "bob")
    cid = _import(client, alice, to_case_csv(make_company()))["company"]["id"]
    assert client.get(f"/api/companies/{cid}/dashboard", headers=bob).status_code == 404
    assert client.post(f"/api/companies/{cid}/events", headers=bob, json={}).status_code in (404, 422)


def test_event_idempotency(client):
    h = _login(client, "alice")
    res = _import(client, h, to_case_csv(make_company()))
    cid, as_of = res["company"]["id"], client.get(f"/api/companies/{res['company']['id']}/dashboard", headers=h) \
        .json()["forecast"]["as_of"]
    key = str(uuid.uuid4())
    day = (__import__("datetime").date.fromisoformat(as_of) + timedelta(days=7)).isoformat()
    body = {"event_date": day, "amount": "300000", "direction": "in", "title": "Клиент обещал"}
    r1 = client.post(f"/api/companies/{cid}/events", headers={**h, "Idempotency-Key": key}, json=body)
    r2 = client.post(f"/api/companies/{cid}/events", headers={**h, "Idempotency-Key": key}, json=body)
    r3 = client.post(f"/api/companies/{cid}/events", headers={**h, "Idempotency-Key": key},
                     json={**body, "amount": "1"})
    assert (r1.status_code, r2.status_code, r3.status_code) == (201, 200, 409)
    assert r1.json()["id"] == r2.json()["id"]
    assert len(client.get(f"/api/companies/{cid}/events", headers=h).json()) == 1


def test_mass_assignment_is_rejected(client):
    h = _login(client, "alice")
    cid = _import(client, h, to_case_csv(make_company()))["company"]["id"]
    r = client.patch(f"/api/companies/{cid}", headers=h, json={"owner_id": "someone-else"})
    assert r.status_code == 422


def test_logs_do_not_leak_inn_or_tokens(caplog):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "платёж ИНН 0012345678 токен Bearer abc.def.ghi", (), None)
    RedactingFilter().filter(record)
    assert "0012345678" not in record.msg and "abc.def.ghi" not in record.msg
    assert redact("ключ sk-proj-AAAAAAAAAAAAAAAA") == "ключ [SECRET]"


def test_integration_client_retries_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        if calls["n"] == 2:
            return httpx.Response(429, headers={"Retry-After": "1"})
        assert request.headers["Authorization"] == "Bearer t0k"   # токен в заголовке, не в URL
        return httpx.Response(200, json={"ok": True})

    c = ResilientClient("http://mock", "t0k", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    assert c.get_json("/x") == {"ok": True} and calls["n"] == 3


def test_integration_client_does_not_retry_client_errors():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400)

    c = ResilientClient("http://mock", "", transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(IntegrationError):
        c.get_json("/x")
    assert calls["n"] == 1
