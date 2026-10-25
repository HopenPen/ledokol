from datetime import date

from sqlalchemy import func, select

from app.api.routes.auth import verification_mailer
from app.core.config import get_settings
from app.db.models import Company, Operation, UserEmail
from app.db.session import SessionLocal
from app.services.signup_demo import PROJECT, RETAIL, seed_user_demo
from tests.test_api import _login
from tests.test_registration import Mailbox


def test_signup_has_two_private_demo_companies_with_useful_forecasts(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "signup_demo_companies", True)
    monkeypatch.setattr(settings, "require_email_verification", False)
    body = {"email": "demo-owner@example.com", "password": "demo-owner-password"}
    assert client.post("/api/auth/register", json=body).status_code == 202
    login = client.post("/api/auth/login", json={"login": body["email"], "password": body["password"]})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    companies = client.get("/api/companies", headers=headers).json()
    assert {c["external_id"] for c in companies} == {RETAIL, PROJECT}
    for company in companies:
        assert company["name"].startswith("Демо ·")
        dashboard = client.get(f"/api/companies/{company['id']}/dashboard", headers=headers)
        assert dashboard.status_code == 200
        forecast = dashboard.json()["forecast"]
        assert len(forecast["points"]) == 30
        assert forecast["low_history"] is False
        assert not forecast["warnings"]
        if company["external_id"] == RETAIL:
            assert forecast["last_balance"] == 1700000
            assert forecast["alerts"] == []
        else:
            assert forecast["last_balance"] == 240000
            assert forecast["alerts"]
            assert any(event["source"] == "manual" for event in forecast["events"])
        assert client.get(f"/api/companies/{company['id']}/dashboard", headers=_login(client, "bob")).status_code == 404
    assert client.post("/api/auth/register", json=body).status_code == 202
    assert len(client.get("/api/companies", headers=headers).json()) == 2


def test_demo_seed_is_idempotent_and_rolls_back(client):
    from app.db.models import User

    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.login == "alice"))
        seed_user_demo(session, user, as_of=date(2026, 10, 23))
        count = session.scalar(select(func.count()).select_from(Operation))
        assert count > 400
        seed_user_demo(session, user, as_of=date(2026, 10, 23))
        assert session.scalar(select(func.count()).select_from(Operation)) == count
        session.rollback()
        assert session.scalar(select(func.count()).select_from(Company)) == 0


def test_failed_email_delivery_does_not_leave_demo_data(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "signup_demo_companies", True)
    monkeypatch.setattr(settings, "require_email_verification", True)
    mailbox = Mailbox()
    mailbox.fail = True
    client.app.dependency_overrides[verification_mailer] = lambda: mailbox
    response = client.post("/api/auth/register", json={"email": "demo-failed@example.com", "password": "password-12345"})
    assert response.status_code == 503
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Company)) == 0
        assert session.scalar(select(func.count()).select_from(UserEmail)) == 0
