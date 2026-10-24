"""Единая банковская выписка: денежные инварианты не зависят от TXT/PDF и БД."""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.ingest import StatementFormatError


@dataclass(frozen=True)
class BankPayment:
    day: date
    number: str
    amount: Decimal
    direction: str
    counterparty_name: str
    counterparty_inn: str = ""
    counterparty_account: str = ""
    purpose: str = ""

    def source_id(self, account: str) -> str:
        # Одна операция сохраняет идентичность при пересечении периодов выписок.
        identity = [account, self.day.isoformat(), self.number, str(self.amount.normalize()), self.direction,
                    self.counterparty_account, " ".join(self.purpose.split())]
        return "bank:" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:58]


@dataclass(frozen=True)
class BalancePeriod:
    start: date
    end: date
    opening: Decimal
    closing: Decimal
    incoming: Decimal | None = None
    outgoing: Decimal | None = None


@dataclass(frozen=True)
class BankStatement:
    account: str
    name: str
    payments: list[BankPayment]
    periods: list[BalancePeriod]

    def operation_rows(self) -> list[dict]:
        periods = sorted(self.periods, key=lambda p: p.start)
        if not periods or any(p.end < p.start for p in periods):
            raise StatementFormatError("В выписке не указан корректный период и остатки")
        if any(a.end >= b.start for a, b in itertools.pairwise(periods)):
            raise StatementFormatError("Периоды внутри выписки пересекаются")
        assigned = [p for period in periods for p in self.payments if period.start <= p.day <= period.end]
        if len(assigned) != len(self.payments):
            raise StatementFormatError("Дата платежа выходит за период выписки")
        result, seen = [], set()
        for period in periods:
            payments = sorted((p for p in self.payments if period.start <= p.day <= period.end),
                              key=lambda p: (p.day, p.number))
            incoming = sum((p.amount for p in payments if p.direction == "in"), Decimal(0))
            outgoing = sum((p.amount for p in payments if p.direction == "out"), Decimal(0))
            if (period.opening + incoming - outgoing != period.closing
                    or (period.incoming is not None and incoming != period.incoming)
                    or (period.outgoing is not None and outgoing != period.outgoing)):
                raise StatementFormatError("Остатки и обороты выписки не сходятся с платежами; файл не загружен")
            balance, daily = period.opening, {}
            for payment in payments:
                if payment.amount <= 0 or payment.direction not in {"in", "out"}:
                    raise StatementFormatError("Некорректная сумма или направление платежа")
                balance += payment.amount if payment.direction == "in" else -payment.amount
                daily[payment.day] = balance
            for payment in payments:
                source_id = payment.source_id(self.account)
                if source_id in seen:
                    raise StatementFormatError("Внутри выписки повторяется один и тот же платёж")
                seen.add(source_id)
                if abs(daily[payment.day]) >= Decimal(100000000000000):
                    raise StatementFormatError("Остаток превышает допустимый размер")
                result.append({"company_id": "bank:" + self.account, "operation_id": source_id,
                                   "operation_date": payment.day.isoformat(), "amount": str(payment.amount),
                                   "direction": "Поступление" if payment.direction == "in" else "Списание",
                                   "counterparty_inn": payment.counterparty_inn,
                                   "counterparty_name": payment.counterparty_name, "payment_purpose": payment.purpose,
                                   "balance_eod": str(daily[payment.day])})
        return result
