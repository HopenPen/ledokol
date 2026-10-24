"""Чтение операций компании из БД в формат, который понимает домен (тот же, что даёт read_statement)."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Operation


def load_operations_frame(session: Session, company: Company, *, with_rows: bool = False):
    rows = list(session.scalars(select(Operation).where(Operation.company_id == company.id)
                                .order_by(Operation.op_date, Operation.source_operation_id)))
    df = pd.DataFrame({
        "company_id": company.external_id,
        "operation_id": [r.source_operation_id for r in rows],
        "operation_date": pd.to_datetime([r.op_date for r in rows]),
        "amount": [float(r.amount) for r in rows],
        "direction": [r.direction for r in rows],
        "counterparty_inn": [r.counterparty_inn or "" for r in rows],
        "counterparty_name": [r.counterparty_name for r in rows],
        "payment_purpose": [r.purpose for r in rows],
        "balance_eod": [float(r.balance_eod) if r.balance_eod is not None else np.nan for r in rows],
        "db_id": [r.id for r in rows],
        "user_category": [r.category if r.category_source == "user" else None for r in rows],
    })
    df["signed"] = np.where(df["direction"].eq("in"), df["amount"], -df["amount"])
    df["cp_key"] = df["counterparty_inn"].where(df["counterparty_inn"].ne(""), df["counterparty_name"])
    return (df, rows) if with_rows else df


def apply_user_categories(ops: pd.DataFrame) -> pd.DataFrame:
    """Ручные правки пользователя главнее модели: подменяем категорию после авторазметки."""
    if "user_category" not in ops or ops["user_category"].isna().all():
        return ops
    ops = ops.copy()
    mask = ops["user_category"].notna()
    ops.loc[mask, "category"] = ops.loc[mask, "user_category"]
    ops.loc[mask, "category_source"] = "user"
    return ops
