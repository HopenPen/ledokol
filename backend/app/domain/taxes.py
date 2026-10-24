"""Налоговый календарь: ЕНП до 28-го (перенос на рабочий день) с квартальным ритмом.

EDA: налоги имеют квартальный ритм (авансы УСН и НДС после квартала) и годовой пик. Поэтому сумму
берём не «как в прошлом месяце», а по тому же месяцу внутри квартала и тому же месяцу прошлого года.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from app.domain.calendar import next_working_day
from app.domain.types import Direction, EventSource, PlannedEvent

ENP_DAY = 28

_VAT_RX = r"(?:в т\.?\s?ч\.?|в том числе)\s*НДС"
_NO_VAT_RX = r"без\s+НДС|НДС не облагается|без налога"


def guess_tax_regime(ops: pd.DataFrame) -> str:
    """Грубая эвристика режима по поступлениям от клиентов: есть НДС → ОСНО, иначе УСН. Пользователь может поправить."""
    inc = ops[ops["direction"].eq("in") & ops["category"].eq("client_payment")]["payment_purpose"]
    if len(inc) < 10:
        return "unknown"
    vat = inc.str.contains(_VAT_RX, case=False, regex=True) & ~inc.str.contains(_NO_VAT_RX, case=False, regex=True)
    return "osno" if vat.mean() > 0.3 else "usn"


def project_taxes(ops: pd.DataFrame, as_of: date, end: date) -> list[PlannedEvent]:
    tax = ops[ops["category"].eq("tax") & ops["quality"].eq("ok") & ops["direction"].eq("out")]
    if tax.empty:
        return []
    monthly = tax.groupby(tax["operation_date"].dt.to_period("M"))["amount"].sum()
    events: list[PlannedEvent] = []
    month = pd.Period(as_of, "M")
    while (due := next_working_day(date(month.year, month.month, ENP_DAY))) <= end:
        already_paid = month in monthly.index and month == pd.Period(as_of, "M") and as_of.day >= ENP_DAY - 7
        if due > as_of and not already_paid:
            amount = _expected_amount(monthly, month)
            if amount > 0:
                events.append(PlannedEvent(
                    event_date=due, amount=amount, direction=Direction.OUT,
                    title="ЕНП по налоговому календарю", category="tax", source=EventSource.CALENDAR,
                    probability=1.0, date_jitter_days=0,
                ))
        month += 1
    return events


def _expected_amount(monthly: pd.Series, month: pd.Period) -> float:
    same_pos = monthly[[(p.month - 1) % 3 == (month.month - 1) % 3 for p in monthly.index]].tail(4)
    base = float(same_pos.median()) if len(same_pos) else float(monthly.median())
    last_year = month - 12
    if last_year in monthly.index:          # годовой пик (декларация, остаток налога за год)
        return 0.5 * base + 0.5 * float(monthly[last_year])
    return base
