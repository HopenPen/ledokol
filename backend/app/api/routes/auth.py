"""Вход, регистрация и подтверждение email."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import DbSession
from app.api.schemas import AuthMessage, LoginIn, RegisterIn, RegistrationInfoOut, ResendVerificationIn, TokenOut, VerifyEmailIn
from app.core.config import get_settings
from app.core.security import create_access_token
from app.integrations.email import SmtpVerificationMailer
from app.services.registration import (
    EmailDeliveryError,
    EmailNotVerified,
    InvalidVerificationToken,
    VerificationMailer,
    authenticate,
    register,
    resend_verification,
    verify_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_MESSAGE = "Если адресу требуется подтверждение, письмо отправлено. Проверьте входящие и папку «Спам»."


def _registration_message() -> str:
    if not get_settings().require_email_verification:
        return "Можно войти с указанным email и паролем."
    return _MESSAGE


def _rate_limit(request: Request, action: str, limit: int) -> None:
    ip = request.client.host if request.client else "unknown"
    now, queue = time.monotonic(), _ATTEMPTS[f"{action}:{ip}"]
    while queue and now - queue[0] > 60:
        queue.popleft()
    if len(queue) >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток, подождите минуту")
    queue.append(now)


def verification_mailer() -> VerificationMailer:
    return SmtpVerificationMailer()


Mailer = Annotated[VerificationMailer, Depends(verification_mailer)]


@router.get("/registration-info", response_model=RegistrationInfoOut)
def registration_info() -> RegistrationInfoOut:
    """Только режим доставки, без SMTP-адреса, логина и секретов."""
    settings = get_settings()
    if not settings.require_email_verification:
        return RegistrationInfoOut(email_delivery="disabled")
    if not settings.smtp_host or settings.smtp_from.endswith("@example.invalid"):
        return RegistrationInfoOut(email_delivery="unavailable")
    local_capture = settings.smtp_host in {"mailpit", "localhost", "127.0.0.1", "::1"} and settings.smtp_port == 1025
    if settings.env != "prod" and local_capture and settings.local_mailbox_url is not None:
        return RegistrationInfoOut(email_delivery="local", local_mailbox_url=str(settings.local_mailbox_url))
    return RegistrationInfoOut(email_delivery="smtp")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, session: DbSession) -> TokenOut:
    _rate_limit(request, "login", 10)
    try:
        user = authenticate(session, body.login, body.password)
    except EmailNotVerified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Подтвердите email по ссылке из письма") from None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/register", response_model=AuthMessage, status_code=status.HTTP_202_ACCEPTED)
def signup(body: RegisterIn, request: Request, session: DbSession, mailer: Mailer) -> AuthMessage:
    _rate_limit(request, "register", 5)
    try:
        register(session, str(body.email), body.password, mailer)
    except EmailDeliveryError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось отправить письмо. Попробуйте позже") from None
    return AuthMessage(message=_registration_message())


@router.post("/resend-verification", response_model=AuthMessage, status_code=status.HTTP_202_ACCEPTED)
def resend(body: ResendVerificationIn, request: Request, session: DbSession, mailer: Mailer) -> AuthMessage:
    _rate_limit(request, "resend", 5)
    try:
        resend_verification(session, str(body.email), mailer)
    except EmailDeliveryError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось отправить письмо. Попробуйте позже") from None
    return AuthMessage(message=_registration_message())


@router.post("/verify-email", response_model=AuthMessage)
def confirm(body: VerifyEmailIn, request: Request, session: DbSession) -> AuthMessage:
    _rate_limit(request, "verify", 20)
    try:
        verify_email(session, body.token)
    except InvalidVerificationToken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка недействительна или срок её действия истёк. Запросите новое письмо") from None
    return AuthMessage(message="Email подтверждён. Теперь можно войти в приложение.")
