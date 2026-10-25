"""Реестр счетов из назначений платежей: разбор, восстановление на дату отсечки, отсутствие подсматривания в будущее."""
from __future__ import annotations

import pandas as pd

from app.domain.invoices import build_registry, has_invoice, open_invoice_events


def _ops(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["operation_date", "direction", "cp_key", "amount", "payment_purpose"]).assign(
        operation_date=lambda d: pd.to_datetime(d["operation_date"]))


def test_invoice_number_and_date_are_parsed_in_all_known_phrasings():
    p = pd.Series(["Оплата по счету № 1499 от 16.06.2025 за поставку", "согласно счету №2827 от 20.07.2026г. Без НДС",
                   "Оплата по договору № 11/23 по счету 883 от 28.03.2025", "Комиссия за ведение счета за июль 2025 г.",
                   "Окончательный расчет по договору № 691-26 от 12.05.2026"])
    assert has_invoice(p).tolist() == [True, True, True, False, False]


def test_registry_merges_partial_payments_of_one_invoice():
    ops = _ops([("2026-03-10", "in", "A", 40.0, "Оплата по счету № 7 от 01.03.2026"),
                ("2026-03-20", "in", "A", 60.0, "Доплата по счету № 7 от 01.03.2026")])
    reg = build_registry(ops)
    assert len(reg) == 1 and reg["amount"].iloc[0] == 100.0 and reg["pay_date"].iloc[0] == pd.Timestamp("2026-03-10")


def test_only_invoices_issued_before_and_paid_after_cutoff_become_events():
    ops = _ops([("2026-03-10", "in", "A", 100.0, "Оплата по счету № 1 от 01.03.2026"),      # оплачен до отсечки
                ("2026-04-20", "in", "A", 200.0, "Оплата по счету № 2 от 25.03.2026"),      # выставлен до, оплачен после
                ("2026-05-30", "in", "A", 300.0, "Оплата по счету № 3 от 10.05.2026")])     # выставлен после отсечки
    events = open_invoice_events(build_registry(ops), pd.Timestamp("2026-04-01"), pd.Timestamp("2026-06-30").date())
    assert [e.ref for e in events] == ["A:2"] and events[0].amount == 200.0


def test_expected_date_uses_history_delay_not_the_actual_payment_date():
    # прошлый счёт клиента закрыт за 10 дней → новый счёт от 25.03 ждём около 04.04, а не 20.04, когда заплатили на деле
    ops = _ops([("2026-03-11", "in", "A", 100.0, "Оплата по счету № 1 от 01.03.2026"),
                ("2026-04-20", "in", "A", 200.0, "Оплата по счету № 2 от 25.03.2026")])
    e = open_invoice_events(build_registry(ops), pd.Timestamp("2026-04-01"), pd.Timestamp("2026-06-30").date())[0]
    assert e.event_date.isoformat() == "2026-04-06"          # 25.03 + 10 дней = 04.04 (суббота) → понедельник


def test_overdue_invoice_is_expected_soon_with_lower_probability():
    ops = _ops([("2026-03-11", "in", "A", 100.0, "Оплата по счету № 1 от 01.03.2026"),
                ("2026-05-20", "in", "A", 200.0, "Оплата по счету № 2 от 25.03.2026")])
    e = open_invoice_events(build_registry(ops), pd.Timestamp("2026-04-30"), pd.Timestamp("2026-06-30").date())[0]
    assert e.event_date.isoformat() == "2026-05-04" and e.probability == 0.5   # 01.05 — праздник, ближайший рабочий 04.05
