"""Вход в прототип. В бою — авторизация банка (OIDC), этот роутер выключается."""
from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import LoginIn, TokenOut
from app.core.security import create_access_token, verify_password
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

# Простой лимит попыток входа: 10 в минуту с одного IP. Для прототипа хватает памяти процесса.
_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
_LIMIT, _WINDOW_S = 10, 60.0


def _rate_limit(ip: str) -> None:
    now, q = time.monotonic(), _ATTEMPTS[ip]
    while q and now - q[0] > _WINDOW_S:
        q.popleft()
    if len(q) >= _LIMIT:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Слишком много попыток, подождите минуту")
    q.append(now)


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, session: DbSession) -> TokenOut:
    _rate_limit(request.client.host if request.client else "unknown")
    user = session.scalar(select(User).where(User.login == body.login))
    # Одна и та же ошибка для «нет пользователя» и «неверный пароль» — нельзя перебором узнать логины.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return TokenOut(access_token=create_access_token(user.id))
