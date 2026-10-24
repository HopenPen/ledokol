"""Пароли (scrypt из stdlib) и JWT. В боевом режиме вход — через авторизацию банка (OIDC), здесь — для прототипа."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_ALG = "HS256"


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, dk_b64 = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=_N, r=_R, p=_P, dklen=_DKLEN)
    return hmac.compare_digest(dk, base64.b64decode(dk_b64))


def create_access_token(user_id: str) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    claims = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes), "typ": "access"}
    return jwt.encode(claims, s.jwt_secret.get_secret_value(), algorithm=_ALG)


def decode_access_token(token: str) -> str | None:
    """id пользователя или None. Причину отказа наружу не отдаём."""
    try:
        claims = jwt.decode(token, get_settings().jwt_secret.get_secret_value(), algorithms=[_ALG],
                            options={"require": ["exp", "sub"]})
    except jwt.PyJWTError:
        return None
    return claims.get("sub") if claims.get("typ") == "access" else None
