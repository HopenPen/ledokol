"""Реестр счетов, восстановленный из назначений платежей (для бэктеста доп. источников, ТЗ 5.1).

В живом приложении неоплаченные счета приходят из 1С. В исторической выписке 1С нет, но номер и дата счёта
написаны в назначении платежа («Оплата по счету № 1499 от 16.06.2025»). По ним можно восстановить, что лежало
бы в реестре на любую дату отсечки: счёт выставлен до отсечки, а оплачен — после.

Что можно использовать на отсечке, а что нельзя (чтобы не подсмотреть в будущее):
- сам факт счёта и его сумма — можно: в реальности счёт был бы в реестре до оплаты;
- дата фактической оплаты — нельзя: ожидаемую дату считаем как дата счёта + типичная задержка этого клиента,
  а задержку оцениваем только по счетам, оплаченным до отсечки.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.domain.calendar import next_working_day
from app.domain.types import CONFIDENCE_PROB, Confidence, Direction, EventSource, PlannedEvent

# «по счету № 1499 от 16.06.2025», «согласно счету №2827 от 20.07.2026г», «по счету 883 от 28.03.2025»
INVOICE_RE = re.compile(r"сч[её]т[а-я]*\s*(?:№|N|#)?\s*([\w/-]+)\s+от\s+(\d{2}\.\d{2}\.\d{4})", re.IGNORECASE)
DEFAULT_DELAY_DAYS = 14          # если по компании нет ни одного закрытого счёта
MAX_DELAY_DAYS = 120


def has_invoice(purpose: pd.Series) -> pd.Series:
    """Булева маска: в назначении есть и номер, и дата счёта."""
    return purpose.fillna("").str.contains(INVOICE_RE)


def build_registry(ops: pd.DataFrame) -> pd.DataFrame:
    """Все счета, упомянутые в назначениях: номер, дата выставления, сумма, направление, контрагент, дата первой оплаты."""
    found = ops["payment_purpose"].fillna("").str.extract(INVOICE_RE)
    mask = found[0].notna()
    reg = pd.DataFrame({
        "number": found.loc[mask, 0], "issue_date": pd.to_datetime(found.loc[mask, 1], format="%d.%m.%Y", errors="coerce"),
        "direction": ops.loc[mask, "direction"], "cp_key": ops.loc[mask, "cp_key"], "amount": ops.loc[mask, "amount"],
        "pay_date": ops.loc[mask, "operation_date"],
    }).dropna(subset=["issue_date"])
    reg = reg[reg["issue_date"] <= reg["pay_date"]]            # дата счёта позже оплаты — опечатка, выбрасываем
    return reg.groupby(["direction", "cp_key", "number"], as_index=False).agg(
        issue_date=("issue_date", "first"), amount=("amount", "sum"), pay_date=("pay_date", "min"))


def _delays(paid: pd.DataFrame) -> tuple[dict, dict]:
    """Типичная задержка оплаты (медиана дней) по контрагенту и по всей компании, отдельно для приходов и расходов."""
    d = (paid["pay_date"] - paid["issue_date"]).dt.days.clip(0, MAX_DELAY_DAYS)
    per_cp = d.groupby([paid["direction"], paid["cp_key"]]).median().to_dict()
    overall = d.groupby(paid["direction"]).median().to_dict()
    return per_cp, overall


def open_invoice_events(registry: pd.DataFrame, cutoff: pd.Timestamp, horizon_end: date) -> list[PlannedEvent]:
    """Счета, которые на дату отсечки уже выставлены, но ещё не оплачены → ожидаемые события."""
    if registry.empty:
        return []
    paid_before = registry[registry["pay_date"] <= cutoff]
    per_cp, overall = _delays(paid_before) if len(paid_before) else ({}, {})
    open_ = registry[(registry["issue_date"] <= cutoff) & (registry["pay_date"] > cutoff)]
    events: list[PlannedEvent] = []
    today = cutoff.date()
    for r in open_.itertuples(index=False):
        delay = per_cp.get((r.direction, r.cp_key), overall.get(r.direction, DEFAULT_DELAY_DAYS))
        due = next_working_day(r.issue_date.date() + timedelta(days=int(delay)))
        overdue = due <= today
        if overdue:                                    # ждали раньше, а деньги не пришли: ожидаем в ближайшие дни
            due = next_working_day(today + timedelta(days=1))
        if due > horizon_end:
            continue
        direction = Direction(r.direction)
        events.append(PlannedEvent(
            event_date=due, amount=float(r.amount), direction=direction, title=f"Счёт № {r.number}",
            category="client_payment" if direction is Direction.IN else "suppliers", source=EventSource.ONEC,
            probability=CONFIDENCE_PROB[Confidence.UNSURE if overdue else Confidence.LIKELY],
            date_jitter_days=3 if direction is Direction.IN else 1, counterparty_key=r.cp_key,
            ref=f"{r.cp_key}:{r.number}"))
    return events
