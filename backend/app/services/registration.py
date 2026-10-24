"""Регистрация и одноразовые подтверждения. Доставка письма подключается через порт VerificationMailer."""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Protocol

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ids import uuid7
from app.core.security import hash_password, verify_password
from app.db.models import User, UserEmail


class EmailDeliveryError(Exception):
    pass


class EmailNotVerified(Exception):
    pass


class InvalidVerificationToken(Exception):
    pass


class VerificationMailer(Protocol):
    def send_verification(self, recipient: str, link: str, ttl_minutes: int) -> None: ...


def email_key(value: str) -> str:
    return validate_email(value, check_deliverability=False).normalized.casefold()


def authenticate(session: Session, login: str, password: str) -> User | None:
    try:
        identity = session.scalar(select(UserEmail).where(UserEmail.email_key == email_key(login.strip())))
    except EmailNotValidError:
        identity = None
    user = session.get(User, identity.user_id) if identity else session.scalar(select(User).where(User.login == login.strip()))
    if user is None or not verify_password(password, user.password_hash):
        return None
    identity = identity or session.get(UserEmail, user.id)
    if identity and identity.verified_at is None:
        raise EmailNotVerified
    return user


def _issue(identity: UserEmail, now: datetime) -> str:
    token = secrets.token_urlsafe(32)
    identity.token_hash = hashlib.sha256(token.encode()).hexdigest()
    identity.expires_at = now + timedelta(minutes=get_settings().verification_ttl_minutes)
    identity.last_sent_at = now
    return token


def _deliver(mailer: VerificationMailer, identity: UserEmail, token: str) -> None:
    settings = get_settings()
    url = settings.public_app_url
    # Origin из конфигурации, а не из Host запроса. Фрагмент не попадает в HTTP-логи и Referer.
    origin = f"{url.scheme}://{url.host}" + (f":{url.port}" if url.port else "")
    mailer.send_verification(identity.email, f"{origin}/verify-email#token={token}", settings.verification_ttl_minutes)


def register(session: Session, email: str, password: str, mailer: VerificationMailer) -> None:
    key = email_key(email)
    if (session.scalar(select(UserEmail).where(UserEmail.email_key == key))
            or session.scalar(select(User).where(func.lower(User.login) == key))):
        return  # одинаковый ответ без раскрытия списка зарегистрированных адресов
    try:
        user = User(login="email:" + uuid7(), password_hash=hash_password(password))
        session.add(user)
        session.flush()
        identity = UserEmail(user_id=user.id, email=email, email_key=key)
        token = _issue(identity, datetime.now(UTC))
        session.add(identity)
        session.flush()
        _deliver(mailer, identity, token)
        session.commit()
    except IntegrityError:
        session.rollback()  # параллельная регистрация того же адреса
        if session.scalar(select(UserEmail).where(UserEmail.email_key == key)) is None:
            raise
    except EmailDeliveryError:
        session.rollback()
        raise


def resend_verification(session: Session, email: str, mailer: VerificationMailer) -> None:
    identity = session.scalar(select(UserEmail).where(UserEmail.email_key == email_key(email)).with_for_update())
    now = datetime.now(UTC)
    if identity is None or identity.verified_at is not None:
        return
    if now - identity.last_sent_at.replace(tzinfo=UTC) < timedelta(seconds=60):
        return
    try:
        token = _issue(identity, now)
        session.flush()
        _deliver(mailer, identity, token)
        session.commit()
    except EmailDeliveryError:
        session.rollback()  # неудачная отправка сохраняет предыдущую действующую ссылку
        raise


def verify_email(session: Session, token: str) -> None:
    result = session.execute(update(UserEmail).where(
        UserEmail.token_hash == hashlib.sha256(token.encode()).hexdigest(), UserEmail.verified_at.is_(None),
        UserEmail.expires_at > datetime.now(UTC))
        .values(verified_at=datetime.now(UTC), token_hash=None, expires_at=None)
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        raise InvalidVerificationToken
    session.commit()
