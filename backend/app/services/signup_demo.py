"""Две независимые демо-компании нового пользователя. Все данные синтетические."""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.models import Company, PlannedEvent
from app.domain.calendar import is_working_day, next_working_day
from app.services.statements import import_statement

RETAIL = "DEMO-SHOP"
PROJECT = "DEMO-PROJECT"


def _history(external, end, target_balance):
    rows = []
    start = end - timedelta(days=300)
    serial = 0
    for offset in range(301):
        day = start + timedelta(days=offset)
        if not is_working_day(day):
            continue
        flows = []
        if external == RETAIL:
            amount = round(48000 * (1 + .07 * math.sin(offset * .71)) * (1.12 if day.weekday() == 0 else 1), 2)
            flows.append(("Поступление", amount, "7700000000", "Демо Банк Эквайринг", "Зачисление выручки по эквайрингу"))
            if day.weekday() == 2:
                flows.append(("Списание", 80000, "7700000010", "Демо Поставщик", "Оплата поставки товара по договору"))
        else:
            flows.append(("Списание", round(1200 * (1 + .05 * math.sin(offset)), 2),
                          "7700000070", "Демо Логистика", "Оплата доставки материалов"))
            for due, amount, inn, name in [(10, 420000, "7700000020", "Демо Крупный клиент"),
                                           (25, 180000, "7700000030", "Демо Второй клиент")]:
                if next_working_day(day.replace(day=due)) == day:
                    flows.append(("Поступление", amount, inn, name, "Оплата выполненных работ по договору"))
            if next_working_day(day.replace(day=18)) == day:
                flows.append(("Списание", 190000, "7700000010", "Демо Поставщик", "Оплата материалов по договору"))
        salary, rent, tax = (160000, 110000, 90000) if external == RETAIL else (110000, 65000, 60000)
        for due, amount, inn, name, purpose in [
            (5, salary, "", "Демо Сотрудники", "Перечисление заработной платы"),
            (20, salary, "", "Демо Сотрудники", "Перечисление аванса по заработной плате"),
            (12, rent, "7700000040", "Демо Арендодатель", "Аренда помещения по договору"),
            (28, tax, "7700000050", "Демо Налоговая", "Единый налоговый платеж ЕНП УСН"),
            (15, 20000, "7700000060", "Демо Связь", "Абонентская плата за связь и программное обеспечение"),
        ]:
            if next_working_day(day.replace(day=due)) == day:
                flows.append(("Списание", amount, inn, name, purpose))
        for direction, amount, inn, name, purpose in flows:
            serial += 1
            rows.append({"company_id": external, "operation_id": f"{external}-{serial:05}",
                         "operation_date": day.isoformat(), "amount": f"{amount:.2f}", "direction": direction,
                         "counterparty_inn": inn, "counterparty_name": name, "payment_purpose": purpose, "balance_eod": ""})
    net = sum(Decimal(row["amount"]) * (1 if row["direction"] == "Поступление" else -1) for row in rows)
    balance = Decimal(target_balance) - net
    for day in sorted({row["operation_date"] for row in rows}):
        daily = [row for row in rows if row["operation_date"] == day]
        balance += sum(Decimal(row["amount"]) * (1 if row["direction"] == "Поступление" else -1) for row in daily)
        for row in daily:
            row["balance_eod"] = f"{balance:.2f}"
    return rows


def seed_user_demo(session, user, *, as_of=None):
    """Участвует в транзакции регистрации, самостоятельно не коммитит."""
    end = as_of or datetime.now(ZoneInfo("Europe/Moscow")).date() - timedelta(days=1)
    while not is_working_day(end):
        end -= timedelta(days=1)
    existing = set(session.scalars(select(Company.external_id).where(Company.owner_id == user.id)))
    rows = []
    for external, balance in [(RETAIL, "1700000"), (PROJECT, "240000")]:
        if external not in existing:
            rows.extend(_history(external, end, balance))
    if not rows:
        return
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    imported = import_statement(session, user, stream.getvalue().encode("utf-8-sig"), commit=False)
    for result in imported:
        company = result.company
        retail = company.external_id == RETAIL
        company.name = "Демо · Розничный магазин" if retail else "Демо · Производство"
        company.industry = "Вымышленные данные: стабильная розница" if retail else "Вымышленные данные: кассовый разрыв"
        company.tax_regime, company.legal_form = "usn", "ООО"
        if not retail:
            for days, amount, direction, title, confidence in [
                (4, 900000, "out", "Демо: оплата оборудования по договору", "certain"),
                (18, 800000, "in", "Демо: ожидаемая оплата крупного клиента", "unsure"),
            ]:
                session.add(PlannedEvent(company_id=company.id, event_date=next_working_day(end + timedelta(days=days)),
                                         amount=Decimal(amount), direction=direction, kind="manual", source="manual",
                                         title=title, confidence=confidence))
    session.flush()
