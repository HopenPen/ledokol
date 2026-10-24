"""Зависимости FastAPI: текущий пользователь и проверка владения компанией.

Владение проверяется на уровне данных, а не только роутом: компания ищется сразу с условием owner_id = user.id.
Чужая компания → 404, а не 403, чтобы нельзя было перебором узнать, какие id существуют.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import Company, User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_session)]


def current_user(session: DbSession,
                 creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> User:
    user_id = decode_access_token(creds.credentials) if creds else None
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owned_company(company_id: str, session: DbSession, user: CurrentUser) -> Company:
    company = session.scalar(select(Company).where(Company.id == company_id, Company.owner_id == user.id))
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    return company


OwnedCompany = Annotated[Company, Depends(owned_company)]
