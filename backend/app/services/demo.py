"""Демо-данные: пользователь + несколько компаний из датасета (кандидаты из EDA: C009 — овердрафт,
C066 — один крупный клиент, C082 — сезонный агробизнес)."""
from __future__ import annotations

import io

import pandas as pd
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.models import User
from app.db.session import Base, SessionLocal, engine
from app.domain.ingest import DIRECTION_MAP
from app.services.statements import import_statement


def seed(ops: pd.DataFrame) -> int:
    s = get_settings()
    if s.demo_password is None:
        raise SystemExit("Задайте CASHFLOW_DEMO_PASSWORD в .env — пароль в коде не храним")
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.login == s.demo_user))
        if user is None:
            user = User(login=s.demo_user, password_hash=hash_password(s.demo_password.get_secret_value()))
            session.add(user)
            session.commit()
        results = import_statement(session, user, to_csv(ops))
    return len(results)


def to_csv(ops: pd.DataFrame) -> bytes:
    """Обратно в формат кейса, чтобы демо шло через тот же импорт, что и у пользователя."""
    back = {v: k for k, v in DIRECTION_MAP.items()}
    df = ops.assign(operation_date=ops["operation_date"].dt.strftime("%Y-%m-%d"),
                    direction=ops["direction"].map(back))
    cols = ["company_id", "operation_id", "operation_date", "amount", "direction", "counterparty_inn",
            "counterparty_name", "payment_purpose", "balance_eod"]
    buf = io.StringIO()
    df[cols].to_csv(buf, sep=";", index=False)
    return buf.getvalue().encode("utf-8-sig")
