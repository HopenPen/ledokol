"""Чтение и проверка выписки: формат кейса, дубли, сверка остатка, «дыры».

Правила выведены из EDA (notebook cashflow_eda.ipynb):
- остаток одинаков для всех операций дня и сходится с потоками в 99,9% дней;
- лишняя строка-дубль НЕ учтена в остатке — это и есть надёжный признак артефакта выгрузки;
- после пропуска ≥ 3 рабочих дней остаток может «скакнуть» — эти дни помечаем, модель потоков на них не учим.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.domain.calendar import is_working_day

REQUIRED_COLUMNS = [
    "company_id", "operation_id", "operation_date", "amount", "direction",
    "counterparty_inn", "counterparty_name", "payment_purpose", "balance_eod",
]
DIRECTION_MAP = {"Поступление": "in", "Списание": "out"}
DUP_KEY = ["company_id", "operation_date", "amount", "direction", "counterparty_inn", "counterparty_name",
           "payment_purpose"]


class StatementFormatError(ValueError):
    """Файл не похож на выписку в формате кейса. Сообщение безопасно показывать пользователю."""


@dataclass(slots=True)
class QualityReport:
    rows_total: int = 0
    rows_rejected: int = 0
    duplicates: int = 0
    gap_days: int = 0
    balance_jumps: int = 0
    empty_purpose: int = 0
    empty_inn: int = 0
    history_working_days: int = 0
    warnings: list[str] = field(default_factory=list)


def read_statement(raw: bytes | str | io.IOBase) -> pd.DataFrame:
    """CSV кейса → DataFrame со строгими типами. ИНН и id читаются строкой (ведущие нули!)."""
    src = io.BytesIO(raw) if isinstance(raw, bytes) else raw
    try:
        df = pd.read_csv(src, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise StatementFormatError("Не удалось прочитать файл: ожидается CSV в UTF-8 с разделителем «;»") from exc
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise StatementFormatError(f"В файле нет обязательных колонок: {', '.join(missing)}")
    return normalize(df)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    out = df[REQUIRED_COLUMNS].copy()
    out["operation_date"] = pd.to_datetime(out["operation_date"], format="%Y-%m-%d", errors="coerce")
    out["amount"] = pd.to_numeric(out["amount"], errors="coerce")
    out["balance_eod"] = pd.to_numeric(out["balance_eod"], errors="coerce")
    out["direction"] = out["direction"].map(DIRECTION_MAP)
    for col in ("counterparty_inn", "counterparty_name", "payment_purpose"):
        out[col] = out[col].fillna("").astype(str).str.strip()
    for col in ("company_id", "operation_id"):
        out[col] = out[col].fillna("").astype(str).str.strip()
    checks = {
        "operation_date": out["operation_date"].notna(),
        "amount": out["amount"].gt(0) & np.isfinite(out["amount"]) & out["amount"].lt(10**14),
        "direction": out["direction"].notna(),
        "balance_eod": np.isfinite(out["balance_eod"]) & out["balance_eod"].abs().lt(10**14),
        "company_id": out["company_id"].str.len().between(1, 32),
        "operation_id": out["operation_id"].str.len().between(1, 64),
        "counterparty_inn": out["counterparty_inn"].str.fullmatch(r"(?:[0-9]{10}|[0-9]{12})?"),
    }
    valid = pd.DataFrame(checks).all(axis=1)
    out.attrs["rows_rejected"] = int((~valid).sum())
    # Только номера записей CSV, без исходных значений, имён и назначений.
    out.attrs["rejected_lines"] = [i + 2 for i, accepted in enumerate(valid) if not accepted][:20]
    out.attrs["invalid_fields"] = [name for name, accepted in checks.items() if not accepted.all()]
    if len(out) and not valid.any():
        lines = ", ".join(map(str, out.attrs["rejected_lines"]))
        fields = ", ".join(out.attrs["invalid_fields"])
        raise StatementFormatError(f"Нет корректных операций. Строки CSV: {lines}. Проверьте поля: {fields}")
    out = out[valid].sort_values(["company_id", "operation_date", "operation_id"]).reset_index(drop=True)
    out["signed"] = np.where(out["direction"].eq("in"), out["amount"], -out["amount"])
    out["cp_key"] = out["counterparty_inn"].where(out["counterparty_inn"].ne(""), out["counterparty_name"])
    return out


def flag_quality(ops: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, QualityReport]:
    """Помечает дубли и дни после «дыр»; возвращает (операции, дневная панель остатка, отчёт).

    Ожидает операции ОДНОЙ компании. Панель — непрерывный ряд по рабочим дням: в дни без операций остаток
    равен предыдущему (так работает выписка), поток = 0.
    """
    rep = QualityReport(rows_total=len(ops), rows_rejected=int(ops.attrs.get("rows_rejected", 0)))
    ops = ops.copy()
    if ops.empty:
        rep.warnings.append("В выписке нет операций")
        return ops.assign(quality="ok"), pd.DataFrame(columns=["date", "balance", "net", "after_gap"]), rep

    ops["quality"] = "ok"
    cand = ops.duplicated(DUP_KEY, keep="first")
    by_day = ops.groupby("operation_date")
    day = pd.DataFrame({
        "net": by_day["signed"].sum(),
        "balance": by_day["balance_eod"].first(),
        "dup_signed": ops[cand].groupby("operation_date")["signed"].sum(),
    }).fillna({"dup_signed": 0.0})
    day["resid"] = (day["balance"] - day["balance"].shift() - day["net"]).round(2)

    # Дубль подтверждён, если без него день сходится: остаток не учитывает лишнюю строку.
    confirmed_days = day.index[(day["dup_signed"] != 0) & ((day["resid"] + day["dup_signed"]).abs() < 0.01)]
    is_dup = cand & ops["operation_date"].isin(confirmed_days)
    ops.loc[is_dup, "quality"] = "duplicate"
    rep.duplicates = int(is_dup.sum())
    clean = ops[~is_dup]

    # Дневная панель на рабочих днях от первой до последней даты.
    span = pd.date_range(clean["operation_date"].min(), clean["operation_date"].max(), freq="D")
    work = pd.DatetimeIndex([d for d in span if is_working_day(d.date())] or [span[0]])
    g = clean.groupby("operation_date")
    panel = pd.DataFrame({"net": g["signed"].sum(), "balance": g["balance_eod"].first()}).reindex(
        work.union(g.size().index))
    panel["has_ops"] = panel["balance"].notna()
    panel["balance"] = panel["balance"].ffill()
    panel["net"] = panel["net"].fillna(0.0)

    # «Дыра»: перед днём с операциями ≥ 3 рабочих дня без операций И остаток не сходится.
    op_days = panel.index[panel["has_ops"]]
    gap_len = pd.Series(np.diff(np.searchsorted(panel.index, op_days), prepend=0) - 1, index=op_days).clip(lower=0)
    resid = (panel.loc[op_days, "balance"] - panel.loc[op_days, "balance"].shift() - panel.loc[op_days, "net"])
    jump_days = op_days[(gap_len >= 3).to_numpy() & (resid.abs() > 0.01).to_numpy()]
    panel["after_gap"] = panel.index.isin(jump_days)
    ops.loc[ops["operation_date"].isin(jump_days) & ops["quality"].eq("ok"), "quality"] = "after_gap"

    rep.gap_days = int((gap_len >= 5).sum())
    rep.balance_jumps = len(jump_days)
    rep.empty_purpose = int(ops["payment_purpose"].eq("").sum())
    rep.empty_inn = int(ops["counterparty_inn"].eq("").sum())
    rep.history_working_days = len(panel)
    if rep.balance_jumps:
        rep.warnings.append(f"В выписке {rep.balance_jumps} пропуск(ов): остаток после них не сходится с операциями")
    if rep.history_working_days < 60:
        rep.warnings.append("История короче 3 месяцев — прогноз приблизительный, используем отраслевые профили")
    panel = panel.rename_axis("date").reset_index()[["date", "balance", "net", "after_gap"]]
    return ops, panel, rep
