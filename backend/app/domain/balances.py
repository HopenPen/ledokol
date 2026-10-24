"""Дневной остаток: начальная сумма + проведённые операции, с опорой на выписку."""
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class BalanceError(ValueError):
    pass


@dataclass(frozen=True)
class Point:
    day: date
    amount: Decimal
    kind: str


def daily_balances(net: dict[date, Decimal], points: Iterable[Point]) -> dict[date, Decimal | None]:
    by_day: dict[date, dict[str, Decimal]] = {}
    for point in points:
        by_day.setdefault(point.day, {})[point.kind] = point.amount
    balance = None
    result = {}
    for day in sorted(net.keys() | by_day.keys()):
        anchors = by_day.get(day, {})
        if "initial" in anchors and balance is None:
            balance = anchors["initial"]  # На начало дня, перед всеми его операциями.
        if balance is not None:
            balance += net.get(day, Decimal(0))
        # Закрывающая сумма банка уже включает операции дня; повторно их не прибавляем.
        balance = anchors.get("statement", anchors.get("legacy", balance))
        if balance is not None and abs(balance) >= Decimal(100000000000000):
            raise BalanceError("Рассчитанный остаток превышает допустимую сумму")
        result[day] = balance
    return result
