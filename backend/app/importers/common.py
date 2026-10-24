"""Строгие преобразования полей внешних банковских форматов."""
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.domain.ingest import StatementFormatError


def money(value: str) -> Decimal:
    try:
        result = Decimal(re.sub(r"[\s\u00a0]", "", value).replace(",", "."))
        if not result.is_finite() or abs(result) >= Decimal(100000000000000) or result != result.quantize(Decimal(".01")):
            raise ValueError
        return result
    except (InvalidOperation, ValueError):
        raise StatementFormatError("Некорректная денежная сумма в выписке") from None


def bank_date(value: str):
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        raise StatementFormatError("Некорректная дата в выписке") from None


def account_number(value: str) -> str:
    if not re.fullmatch(r"\d{20}", value) or value[5:8] not in {"810", "643"}:
        raise StatementFormatError("Поддерживаются только рублёвые счета из 20 цифр")
    return value


def inn(value: str) -> str:
    value = value.strip()
    if value and not re.fullmatch(r"\d{10}|\d{12}", value):
        raise StatementFormatError("Некорректный ИНН в выписке")
    return value
