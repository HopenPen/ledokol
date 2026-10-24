"""Клиент 1С: счета на оплату (выставленные клиентам и полученные от поставщиков).

Формат ответа повторяет OData-интерфейс 1С («standard.odata»): массив `value` и ссылка `odata.nextLink`
для постраничной выдачи. Поля по-русски, как в типовых конфигурациях.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.integrations.http import ResilientClient

DOC_ISSUED = "Document_СчетНаОплатуПокупателю"     # мы выставили → ждём поступление
DOC_RECEIVED = "Document_СчетНаОплатуПоставщика"   # нам выставили → будет списание


@dataclass(frozen=True, slots=True)
class Invoice:
    ref: str
    number: str
    issued: date
    due: date
    amount: Decimal
    counterparty_inn: str | None
    counterparty_name: str
    incoming: bool          # True — платим мы (счёт поставщика)


class OneCClient:
    def __init__(self, http: ResilientClient) -> None:
        self._http = http

    def open_invoices(self, company_external_id: str, as_of: date) -> list[Invoice]:
        out: list[Invoice] = []
        for doc, incoming in ((DOC_ISSUED, False), (DOC_RECEIVED, True)):
            params: dict | None = {"company": company_external_id, "as_of": as_of.isoformat(),
                                   "$filter": "Оплачен eq false", "$top": 100}
            path = f"/odata/standard.odata/{doc}"
            while path:
                page = self._http.get_json(path, params)
                out += [self._parse(row, incoming) for row in page.get("value", [])]
                path, params = page.get("odata.nextLink"), None   # nextLink уже содержит все параметры
        return out

    @staticmethod
    def _parse(row: dict, incoming: bool) -> Invoice:
        cp = row.get("Контрагент") or {}
        return Invoice(
            ref=str(row["Ref_Key"]), number=str(row.get("Номер", "")),
            issued=date.fromisoformat(row["Дата"][:10]), due=date.fromisoformat(row["СрокОплаты"][:10]),
            amount=Decimal(str(row["СуммаДокумента"])), counterparty_inn=cp.get("ИНН") or None,
            counterparty_name=str(cp.get("Наименование", "")), incoming=incoming,
        )
