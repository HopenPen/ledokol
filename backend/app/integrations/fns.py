"""Клиент реестров ФНС: статус контрагента (действует / ликвидация / исключён) и налоговая задолженность.

Зачем прогнозу: если клиент в ликвидации или с долгами перед бюджетом, его оплата по счёту менее вероятна —
снижаем вероятность события, и это сразу отражается в риске разрыва.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.integrations.http import IntegrationError, ResilientClient


@dataclass(frozen=True, slots=True)
class CounterpartyStatus:
    inn: str
    status: str            # active | liquidating | liquidated | unknown
    has_tax_debt: bool

    @property
    def risky(self) -> bool:
        return self.status in {"liquidating", "liquidated"} or self.has_tax_debt


class FnsClient:
    def __init__(self, http: ResilientClient) -> None:
        self._http = http

    def check(self, inn: str) -> CounterpartyStatus:
        if not inn.isdigit() or len(inn) not in (10, 12):
            return CounterpartyStatus(inn, "unknown", False)
        try:
            data = self._http.get_json(f"/api/v1/egr/{inn}")
        except IntegrationError as exc:
            if str(exc) == "http_404":
                return CounterpartyStatus(inn, "unknown", False)
            raise
        return CounterpartyStatus(inn, data.get("status", "unknown"), bool(data.get("tax_debt", False)))
