"""Производственный календарь РФ: какие дни рабочие.

В выписке есть операции только по рабочим дням (README датасета). Для истории календарь берём из самих данных,
для будущего — правило «пн–пт минус праздники» + явные переносы. Переносы на 2026–2027 надо сверить
с постановлением Правительства (TODO перед защитой) — пока список можно дополнять без правки кода.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

# Нерабочие праздничные дни (ст. 112 ТК РФ), без учёта переносов.
_FIXED_HOLIDAYS = {(1, d) for d in range(1, 9)} | {(2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4)}

# Переносы: дата -> True (рабочая суббота) / False (дополнительный выходной). Дополнять по постановлению.
TRANSFERS: dict[date, bool] = {
    date(2025, 11, 1): True,
    date(2025, 11, 3): False,
    date(2025, 12, 31): False,
    date(2026, 1, 9): False,
    date(2026, 12, 31): False,
}


@lru_cache(maxsize=4096)
def is_working_day(d: date) -> bool:
    if d in TRANSFERS:
        return TRANSFERS[d]
    if (d.month, d.day) in _FIXED_HOLIDAYS:
        return False
    return d.weekday() < 5


def next_working_day(d: date, *, inclusive: bool = True) -> date:
    """Ближайший рабочий день (сам d, если он рабочий и inclusive). Так переносятся сроки налогов."""
    cur = d if inclusive else d + timedelta(days=1)
    while not is_working_day(cur):
        cur += timedelta(days=1)
    return cur


def working_days_after(start: date, n: int) -> list[date]:
    """n рабочих дней строго после start."""
    out: list[date] = []
    cur = start
    while len(out) < n:
        cur += timedelta(days=1)
        if is_working_day(cur):
            out.append(cur)
    return out


def history_calendar(dates: pd.Series | pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Календарь рабочих дней по факту: объединение дат операций (по многим компаниям — почти полный)."""
    return pd.DatetimeIndex(sorted(pd.to_datetime(pd.Series(dates)).dt.normalize().unique()))
