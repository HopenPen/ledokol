"""Пользователь должен видеть, куда на самом деле отправляется подтверждение."""
from app.api.routes import auth
from app.core.config import Settings


def test_registration_defaults_to_no_email_verification(monkeypatch):
    monkeypatch.delenv("CASHFLOW_REQUIRE_EMAIL_VERIFICATION", raising=False)
    assert Settings(_env_file=None, env="test").require_email_verification is False


def test_registration_info_disabled_needs_no_smtp(client, monkeypatch):
    settings = Settings(_env_file=None, env="test", require_email_verification=False, smtp_host=None)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    assert client.get("/api/auth/registration-info").json() == {
        "email_delivery": "disabled", "local_mailbox_url": None}


def test_registration_info_reports_missing_smtp(client, monkeypatch):
    monkeypatch.setattr(auth, "get_settings", lambda: Settings(_env_file=None, env="test", smtp_host=None))
    response = client.get("/api/auth/registration-info")
    assert response.status_code == 200
    assert response.json() == {"email_delivery": "unavailable", "local_mailbox_url": None}


def test_registration_info_does_not_disclose_smtp_credentials(client, monkeypatch):
    settings = Settings(_env_file=None, env="test", smtp_host="smtp.provider.test", smtp_user="secret-login",
                        smtp_password="secret-password", smtp_from="no-reply@example.com",
                        local_mailbox_url="http://localhost:8025")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    response = client.get("/api/auth/registration-info")
    assert response.json() == {"email_delivery": "smtp", "local_mailbox_url": None}
    assert "secret" not in response.text and "provider.test" not in response.text


def test_local_mailbox_can_be_disabled_with_empty_env_value():
    assert Settings(_env_file=None, env="test", local_mailbox_url="").local_mailbox_url is None


def test_registration_info_explains_local_mailbox(client, monkeypatch):
    settings = Settings(_env_file=None, env="dev", smtp_host="mailpit", smtp_port=1025, smtp_security="none",
                        smtp_from="no-reply@ledokol.local", local_mailbox_url="http://localhost:8025")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    assert client.get("/api/auth/registration-info").json() == {
        "email_delivery": "local", "local_mailbox_url": "http://localhost:8025/"}


def test_production_never_exposes_local_mailbox(client, monkeypatch):
    settings = Settings(_env_file=None, env="prod", jwt_secret="unit-test-secret-with-more-than-32-characters",
                        smtp_host="smtp.provider.test", smtp_from="no-reply@example.com",
                        public_app_url="https://app.example.com", local_mailbox_url="http://localhost:8025")
    monkeypatch.setattr(auth, "get_settings", lambda: settings)
    assert client.get("/api/auth/registration-info").json() == {
        "email_delivery": "smtp", "local_mailbox_url": None}
