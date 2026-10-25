"""Общие фикстуры. Синтетическая компания собирается детерминированно (seed), без чтения датасета —
тесты идут за секунды и не зависят от того, где лежат данные кейса."""
from __future__ import annotations

import os
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

# Тестовое окружение: своя БД в памяти, тестовые секреты. Задаём ДО импорта приложения.
os.environ.setdefault("CASHFLOW_ENV", "test")
os.environ.setdefault("CASHFLOW_LLM_MCP_ENABLED", "false")
os.environ.setdefault("CASHFLOW_SIGNUP_DEMO_COMPANIES", "false")
os.environ.setdefault("CASHFLOW_REQUIRE_EMAIL_VERIFICATION", "true")
os.environ.setdefault("CASHFLOW_DATABASE_URL", "sqlite:///./test_cashflow.db")
os.environ.setdefault("CASHFLOW_JWT_SECRET", "test-secret-test-secret-test-secret-123")

from app.domain.calendar import is_working_day, next_working_day

PURPOSES = {
    "acq": "Зачисление средств по операциям эквайринга. Мерчант №123. Сумма операций {a}",
    "rent": "Оплата аренды нежилого помещения по договору № 7 за {m} г. Без НДС",
    "salary": "Заработная плата за {m} г. Перечисление на счет сотрудника. НДС не облагается",
    "tax": "Единый налоговый платеж",
    "supplier": "Оплата по счету № {n} от 01.02.2026 за товар",
    "client": "Оплата по счету № {n} от 05.01.2026 за продукцию",
}


def _due_today(d: date, day: int) -> bool:
    """Платёж со сроком `day` числа проводится сегодня (с переносом с выходных на рабочий день)."""
    try:
        due = date(d.year, d.month, day)
    except ValueError:
        return False
    return next_working_day(due) == d


def make_company(start: date = date(2025, 10, 1), days: int = 220, seed: int = 1, start_balance: float = 400_000,
                 company_id: str = "T001", rent: float = 150_000) -> pd.DataFrame:
    """Розница: ежедневный эквайринг, аренда 10-го, зарплата 5-го и 20-го, ЕНП 28-го, закупки, редкие клиенты."""
    rng = np.random.default_rng(seed)
    rows, bal, n = [], start_balance, 0
    for i in range(days):
        d = start + timedelta(days=i)
        if not is_working_day(d):
            continue
        day_ops = []
        mult = 2.5 if d.weekday() == 0 else 1.0
        day_ops.append(("in", round(rng.normal(30_000, 5_000) * mult, 2), "0011111111", "ПАО «Банк»", PURPOSES["acq"].format(a=1)))
        # Как в жизни: если срок выпал на выходной, платят в ближайший рабочий день.
        if _due_today(d, 10):
            day_ops.append(("out", rent, "0022222222", "ООО «Арендодатель»", PURPOSES["rent"].format(m=d.month)))
        if _due_today(d, 5) or _due_today(d, 20):
            day_ops.append(("out", 120_000.0, "", "Сотрудник 01", PURPOSES["salary"].format(m=d.month)))
        if _due_today(d, 28):
            day_ops.append(("out", 60_000.0, "0033333333", "Казначейство России (ФНС России)", PURPOSES["tax"]))
        if rng.random() < 0.3:
            day_ops.append(("out", round(rng.uniform(20_000, 80_000), 2), "0044444444", "ООО «Поставщик»",
                            PURPOSES["supplier"].format(n=n)))
        if rng.random() < 0.05:
            day_ops.append(("in", round(rng.uniform(50_000, 200_000), 2), "0055555555", "ООО «Клиент»",
                            PURPOSES["client"].format(n=n)))
        bal += sum(a if dr == "in" else -a for dr, a, *_ in day_ops)
        for dr, a, inn, name, purpose in day_ops:
            n += 1
            rows.append({"company_id": company_id, "operation_id": f"{company_id}-{n:06d}", "operation_date": pd.Timestamp(d),
                         "amount": a, "direction": dr, "counterparty_inn": inn, "counterparty_name": name,
                         "payment_purpose": purpose, "balance_eod": round(bal, 2)})
    df = pd.DataFrame(rows)
    df["signed"] = np.where(df["direction"].eq("in"), df["amount"], -df["amount"])
    df["cp_key"] = df["counterparty_inn"].where(df["counterparty_inn"].ne(""), df["counterparty_name"])
    return df


def to_case_csv(df: pd.DataFrame) -> bytes:
    out = df.assign(operation_date=df["operation_date"].dt.strftime("%Y-%m-%d"),
                    direction=df["direction"].map({"in": "Поступление", "out": "Списание"}))
    cols = ["company_id", "operation_id", "operation_date", "amount", "direction", "counterparty_inn",
            "counterparty_name", "payment_purpose", "balance_eod"]
    return out[cols].to_csv(sep=";", index=False).encode("utf-8-sig")


@pytest.fixture
def company_ops() -> pd.DataFrame:
    return make_company()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.api.routes import auth
    from app.core.security import hash_password
    from app.db.models import User
    from app.db.session import Base, SessionLocal, engine
    from app.main import create_app

    auth._ATTEMPTS.clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.add_all([User(login="alice", password_hash=hash_password("pw-alice")),
                         User(login="bob", password_hash=hash_password("pw-bob"))])
        session.commit()
    with TestClient(create_app()) as test_client:
        yield test_client
