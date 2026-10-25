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

from app.core.config import get_settings
from app.core.security import decode_access_token
from app.db.models import Company, Operation, OperationAttachment, User
from app.db.session import get_session

_bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_session)]


def current_user(session: DbSession,
                 creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> User:
    user_id = decode_access_token(creds.credentials) if creds else None
    user = session.get(User, user_id) if user_id else None
    if user is None and get_settings().dev_no_auth:
        return _dev_user(session)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход", headers={"WWW-Authenticate": "Bearer"})
    return user


def _dev_user(session: Session) -> User:
    """Локальный просмотр без входа (CASHFLOW_DEV_NO_AUTH=1): один общий пользователь с непригодным для входа паролем."""
    user = session.scalar(select(User).where(User.login == "dev"))
    if user is None:
        user = User(login="dev", password_hash="!")
        session.add(user)
        session.commit()
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def owned_company(company_id: str, session: DbSession, user: CurrentUser) -> Company:
    company = session.scalar(select(Company).where(Company.id == company_id, Company.owner_id == user.id))
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Компания не найдена")
    return company


OwnedCompany = Annotated[Company, Depends(owned_company)]


def owned_operation(operation_id: str, session: DbSession, user: CurrentUser) -> Operation:
    operation = session.scalar(select(Operation).join(Company).where(
        Operation.id == operation_id, Company.owner_id == user.id))
    if operation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Операция не найдена')
    return operation


def owned_attachment(attachment_id: str, session: DbSession, user: CurrentUser) -> OperationAttachment:
    attachment = session.scalar(select(OperationAttachment).join(Operation).join(Company).where(
        OperationAttachment.id == attachment_id, Company.owner_id == user.id))
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, 'Файл не найден')
    return attachment


OwnedOperation = Annotated[Operation, Depends(owned_operation)]
OwnedAttachment = Annotated[OperationAttachment, Depends(owned_attachment)]
