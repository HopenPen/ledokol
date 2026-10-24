"""Вход, регистрация и подтверждение email."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import DbSession
from app.api.schemas import AuthMessage, LoginIn, RegisterIn, ResendVerificationIn, TokenOut, VerifyEmailIn
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
    return AuthMessage(message=_MESSAGE)


@router.post("/resend-verification", response_model=AuthMessage, status_code=status.HTTP_202_ACCEPTED)
def resend(body: ResendVerificationIn, request: Request, session: DbSession, mailer: Mailer) -> AuthMessage:
    _rate_limit(request, "resend", 5)
    try:
        resend_verification(session, str(body.email), mailer)
    except EmailDeliveryError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Не удалось отправить письмо. Попробуйте позже") from None
    return AuthMessage(message=_MESSAGE)


@router.post("/verify-email", response_model=AuthMessage)
def confirm(body: VerifyEmailIn, request: Request, session: DbSession) -> AuthMessage:
    _rate_limit(request, "verify", 20)
    try:
        verify_email(session, body.token)
    except InvalidVerificationToken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ссылка недействительна или срок её действия истёк. Запросите новое письмо") from None
    return AuthMessage(message="Email подтверждён. Теперь можно войти в приложение.")
