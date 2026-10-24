"""Справочник категорий. Роль категории в прогнозе задаётся здесь, а не разбросана по коду."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    RETAIL_REVENUE = "retail_revenue"   # слой B: ежедневная выручка (эквайринг, СБП, наличные, маркетплейсы)
    OPERATING = "operating"             # слои A/C: обычная операционная деятельность
    OWNER = "owner"                     # деньги владельца: реакция на разрыв, а не план → в прогноз не идут
    TRANSFER = "transfer"               # переводы между своими счетами → в прогноз не идут
    FINANCING = "financing"             # получение кредита — разовое, только как известное событие


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    code: str
    label: str
    role: Role
    mandatory: bool = False   # обязательный платёж: его нельзя «просто перенести» в рекомендациях


_C = CategoryInfo
CATEGORIES: dict[str, CategoryInfo] = {c.code: c for c in [
    # поступления
    _C("acquiring", "Эквайринг (карты)", Role.RETAIL_REVENUE),
    _C("sbp", "СБП (QR)", Role.RETAIL_REVENUE),
    _C("cash", "Наличная выручка", Role.RETAIL_REVENUE),
    _C("marketplace", "Маркетплейсы: выплаты", Role.RETAIL_REVENUE),
    _C("client_payment", "Оплата от клиентов", Role.OPERATING),
    _C("owner_in", "Займ / пополнение от владельца", Role.OWNER),
    _C("loan_in", "Кредит получен", Role.FINANCING),
    _C("own_transfer_in", "Перевод со своего счёта", Role.TRANSFER),
    _C("refund_in", "Возврат / ошибочный платёж", Role.OPERATING),
    _C("subsidy", "Субсидии, страховка", Role.OPERATING),
    # списания
    _C("tax", "Налоги (ЕНП)", Role.OPERATING, mandatory=True),
    _C("enforcement", "Взыскание по исп. листу", Role.OPERATING, mandatory=True),
    _C("salary", "Зарплата", Role.OPERATING, mandatory=True),
    _C("gph", "ГПХ / самозанятые", Role.OPERATING),
    _C("owner_out", "Вывод владельцу / дивиденды", Role.OPERATING),
    _C("bank_fees", "Банк: комиссии", Role.OPERATING, mandatory=True),
    _C("loan_payment", "Кредиты и проценты", Role.OPERATING, mandatory=True),
    _C("leasing", "Лизинг", Role.OPERATING, mandatory=True),
    _C("rent", "Аренда", Role.OPERATING, mandatory=True),
    _C("utilities", "Коммунальные услуги", Role.OPERATING, mandatory=True),
    _C("own_transfer_out", "Перевод на свой счёт", Role.TRANSFER),
    _C("refund_out", "Возврат покупателю", Role.OPERATING),
    _C("marketing", "Реклама и маркетинг", Role.OPERATING),
    _C("it_accounting", "Связь, ПО, бухгалтерия", Role.OPERATING),
    _C("logistics", "Логистика и топливо", Role.OPERATING),
    _C("facility", "Хоз. услуги", Role.OPERATING),
    _C("capex", "Ремонт и оборудование", Role.OPERATING),
    _C("suppliers", "Закупки у поставщиков", Role.OPERATING),
    _C("other", "Прочее", Role.OPERATING),
    _C("unknown", "Не определено", Role.OPERATING),
]}

EXCLUDED_FROM_FORECAST = {c for c, i in CATEGORIES.items() if i.role in (Role.OWNER, Role.TRANSFER, Role.FINANCING)}
RETAIL = {c for c, i in CATEGORIES.items() if i.role is Role.RETAIL_REVENUE}


def label(code: str) -> str:
    return CATEGORIES.get(code, CATEGORIES["unknown"]).label
