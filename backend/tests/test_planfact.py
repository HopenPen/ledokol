"""План-факт и черновик: сценарий звёздочки 2 целиком, на настоящей SQLite."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pandas as pd
import pytest

from app.domain.planfact import compare_daily
from tests.conftest import make_company, to_case_csv
from tests.test_api import _import, _login, client  # noqa: F401 — фикстура client


def test_compare_daily_flags_only_out_of_range():
    panel = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-02"]), "balance": [100.0, 500.0]})
    rows = compare_daily([(date(2026, 10, 1), 50, 100, 150), (date(2026, 10, 2), 50, 100, 150),
                          (date(2026, 10, 5), 0, 0, 0)], panel)
    assert [r.flagged for r in rows] == [False, True]   # 500 вне 50–150; 5-е октября ещё без факта — пропущено
    assert rows[1].deviation == 400


@pytest.fixture()
def staged(client):  # noqa: F811
    """Компания загружена до отсечки; остаток выписки — «следующая неделя»."""
    h = _login(client, "alice")
    full = make_company(days=240)
    cut = full["operation_date"].min() + timedelta(days=200)
    cid = _import(client, h, to_case_csv(full[full["operation_date"] <= cut]))["company"]["id"]
    return client, h, cid, full


def test_forecast_snapshot_is_saved_once(staged):
    client, h, cid, _ = staged
    client.get(f"/api/companies/{cid}/dashboard", headers=h)
    client.get(f"/api/companies/{cid}/dashboard", headers=h)   # те же данные → тот же снимок
    from app.db.models import ForecastRun
    from app.db.session import SessionLocal

    with SessionLocal() as s:
        assert s.query(ForecastRun).count() == 1


def test_missed_payment_flow(staged):
    client, h, cid, full = staged
    dash = client.get(f"/api/companies/{cid}/dashboard", headers=h).json()
    as_of = date.fromisoformat(dash["forecast"]["as_of"])
    promised = (as_of + timedelta(days=3)).isoformat()
    client.post(f"/api/companies/{cid}/events", headers={**h, "Idempotency-Key": str(uuid.uuid4())},
                json={"event_date": promised, "amount": "777777", "direction": "in", "title": "Клиент обещал"})
    client.get(f"/api/companies/{cid}/dashboard", headers=h)          # снимок прогноза с обещанным платежом

    # Пришла выписка за следующие 2 недели — обещанных 777 777 ₽ в ней нет.
    upto = pd.Timestamp(as_of + timedelta(days=14))
    client.post(f"/api/companies/{cid}/statements", headers=h,
                files={"file": ("s.csv", to_case_csv(full[full["operation_date"] <= upto]), "text/csv")})

    dash2 = client.get(f"/api/companies/{cid}/dashboard", headers=h).json()
    assert [e["title"] for e in dash2["missed_payments"]] == ["Клиент обещал"]
    assert all(e["title"] != "Клиент обещал" for e in dash2["forecast"]["events"])   # из прогноза ушло

    daily = client.get(f"/api/companies/{cid}/plan-fact/daily", headers=h).json()
    assert daily["run"] is not None and len(daily["rows"]) >= 5
    # План ждал +777 777 ₽, их не было — факт уходит вниз от плана после даты обещания.
    after = [r for r in daily["rows"] if r["date"] > promised]
    assert after and all(r["deviation"] < 0 for r in after)


def test_reschedule_missed_payment(staged):
    client, h, cid, _ = staged
    as_of = date.fromisoformat(client.get(f"/api/companies/{cid}/dashboard", headers=h).json()["forecast"]["as_of"])
    ev = client.post(f"/api/companies/{cid}/events", headers={**h, "Idempotency-Key": str(uuid.uuid4())},
                     json={"event_date": (as_of + timedelta(days=2)).isoformat(), "amount": "1000",
                           "direction": "in", "title": "Перенос"}).json()
    new_day = (as_of + timedelta(days=20)).isoformat()
    r = client.patch(f"/api/companies/{cid}/events/{ev['id']}", headers=h, json={"event_date": new_day})
    assert r.status_code == 200 and r.json()["event_date"] == new_day and r.json()["status"] == "expected"


def test_preview_does_not_persist(staged):
    client, h, cid, _ = staged
    base = client.get(f"/api/companies/{cid}/dashboard", headers=h).json()["forecast"]
    day = base["points"][3]["date"]
    prev = client.post(f"/api/companies/{cid}/forecast/preview", headers=h,
                       json={"extra_events": [{"event_date": day, "amount": "500000", "direction": "in",
                                               "title": "А если придёт"}]}).json()
    assert prev["points"][-1]["p50"] > base["points"][-1]["p50"] + 400_000
    assert client.get(f"/api/companies/{cid}/events", headers=h).json() == []   # черновик ничего не записал
