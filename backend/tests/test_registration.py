"""Регистрация, проверка владения email, срок ссылки и безопасные повторы."""
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select

from app.api.routes.auth import verification_mailer
from app.core.config import get_settings
from app.db.models import User, UserEmail
from app.db.session import SessionLocal
from app.services.registration import EmailDeliveryError

EMAIL, PASSWORD = "Owner@example.com", " correct horse "


class Mailbox:
    def __init__(self):
        self.messages = []
        self.fail = False

    def send_verification(self, recipient, link, ttl_minutes):
        if self.fail:
            raise EmailDeliveryError
        self.messages.append((recipient, link, ttl_minutes))

    def token(self):
        return parse_qs(urlsplit(self.messages[-1][1]).fragment)["token"][0]


@pytest.fixture
def mailbox(client):
    box = Mailbox()
    client.app.dependency_overrides[verification_mailer] = lambda: box
    return box


def signup(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def login(client, email=EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"login": email, "password": password})


def test_registration_requires_single_use_confirmation_and_preserves_password(client, mailbox):
    response = signup(client)
    assert response.status_code == 202 and "access_token" not in response.json()
    token = mailbox.token()
    with SessionLocal() as session:
        identity = session.scalar(select(UserEmail))
        assert identity.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert identity.token_hash != token and identity.verified_at is None
        internal_login = session.get(User, identity.user_id).login
    assert login(client).status_code == 403
    assert login(client, internal_login).status_code == 403
    assert login(client, password=PASSWORD.strip()).status_code == 401
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 400
    authenticated = login(client, "OWNER@EXAMPLE.COM")
    assert authenticated.status_code == 200
    headers = {"Authorization": "Bearer " + authenticated.json()["access_token"]}
    assert client.get("/api/companies", headers=headers).json() == []
    with SessionLocal() as session:
        identity = session.scalar(select(UserEmail))
        assert identity.verified_at is not None and identity.token_hash is None


def test_duplicate_registration_does_not_change_password_or_send_email(client, mailbox):
    first = signup(client)
    second = signup(client, "OWNER@example.com", "attacker-password")
    assert first.json() == second.json() and second.status_code == 202
    assert len(mailbox.messages) == 1
    client.post("/api/auth/verify-email", json={"token": mailbox.token()})
    assert login(client).status_code == 200
    assert login(client, password="attacker-password").status_code == 401


def test_expired_token_and_resend_rotation(client, mailbox):
    signup(client)
    old = mailbox.token()
    assert client.post("/api/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    assert len(mailbox.messages) == 1  # пауза между письмами
    with SessionLocal() as session:
        identity = session.scalar(select(UserEmail))
        identity.last_sent_at = datetime.now(UTC) - timedelta(minutes=2)
        identity.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert client.post("/api/auth/verify-email", json={"token": old}).status_code == 400
    assert client.post("/api/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    assert len(mailbox.messages) == 2 and old != mailbox.token()
    assert client.post("/api/auth/verify-email", json={"token": old}).status_code == 400
    assert client.post("/api/auth/verify-email", json={"token": mailbox.token()}).status_code == 200
    client.post("/api/auth/resend-verification", json={"email": EMAIL})
    assert len(mailbox.messages) == 2


def test_delivery_failure_rolls_back_registration_and_token_rotation(client, mailbox):
    mailbox.fail = True
    assert signup(client).status_code == 503
    with SessionLocal() as session:
        assert session.scalar(select(UserEmail)) is None
        assert len(list(session.scalars(select(User)))) == 2  # только старые alice/bob
    mailbox.fail = False
    assert signup(client).status_code == 202
    token = mailbox.token()
    with SessionLocal() as session:
        session.scalar(select(UserEmail)).last_sent_at = datetime.now(UTC) - timedelta(minutes=2)
        session.commit()
    mailbox.fail = True
    assert client.post("/api/auth/resend-verification", json={"email": EMAIL}).status_code == 503
    assert client.post("/api/auth/verify-email", json={"token": token}).status_code == 200


def test_validation_unknown_email_and_rate_limits(client, mailbox):
    for email, password in [("invalid", "long-password"), (EMAIL, "short")]:
        assert signup(client, email, password).status_code == 422
    unknown = client.post("/api/auth/resend-verification", json={"email": EMAIL})
    assert unknown.status_code == 202 and mailbox.messages == []
    response = signup(client)
    assert response.json() == unknown.json()
    for _ in range(4):
        assert signup(client).status_code == 202
    assert signup(client).status_code == 429
    assert client.post("/api/auth/verify-email", json={"token": "x" * 43}).status_code == 400
    assert login(client).status_code == 403  # лимиты действий не мешают друг другу


def test_temporary_registration_without_email_keeps_password_and_company_isolation(client, mailbox, monkeypatch):
    monkeypatch.setattr(get_settings(), "require_email_verification", False)
    mailbox.fail = True  # SMTP не нужен даже при полной недоступности провайдера.
    first = signup(client)
    assert first.status_code == 202 and "временно отключено" in first.json()["message"]
    assert signup(client, "OWNER@example.com", "attacker-password").json() == first.json()
    assert mailbox.messages == []
    assert login(client, password="attacker-password").status_code == 401
    response = login(client, "OWNER@EXAMPLE.COM")
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/api/companies", headers=headers).json() == []
    owner_login = client.post("/api/auth/login", json={"login": "alice", "password": "pw-alice"})
    owner_headers = {"Authorization": "Bearer " + owner_login.json()["access_token"]}
    created = client.post("/api/companies", json={"name": "Чужая компания"}, headers=owner_headers)
    assert created.status_code == 201
    foreign_company = created.json()["id"]
    with SessionLocal() as session:
        identity = session.scalar(select(UserEmail))
        assert identity.verified_at is None and identity.token_hash is None and identity.expires_at is None
    assert client.get(f"/api/companies/{foreign_company}", headers=headers).status_code == 404
    assert client.post("/api/auth/resend-verification", json={"email": EMAIL}).json() == first.json()
    assert mailbox.messages == []
    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    assert login(client).status_code == 403
    mailbox.fail = False
    assert client.post("/api/auth/resend-verification", json={"email": EMAIL}).status_code == 202
    assert client.post("/api/auth/verify-email", json={"token": mailbox.token()}).status_code == 200
    assert login(client).status_code == 200


def test_temporary_mode_allows_existing_pending_account_without_changing_verification(client, mailbox, monkeypatch):
    signup(client)
    token = mailbox.token()
    assert login(client).status_code == 403
    monkeypatch.setattr(get_settings(), "require_email_verification", False)
    assert login(client).status_code == 200
    with SessionLocal() as session:
        identity = session.scalar(select(UserEmail))
        assert identity.verified_at is None
        assert identity.token_hash == hashlib.sha256(token.encode()).hexdigest()
    monkeypatch.setattr(get_settings(), "require_email_verification", True)
    assert login(client).status_code == 403
