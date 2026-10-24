from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.domain.calendar import next_working_day
from app.domain.categorize import categorize, rule_category


@pytest.mark.parametrize("text", ["Единый налоговый платеж", "ЕНП", "Единый налоговый платёж. НДС не облагается"])
def test_tax_wording_variants_map_to_one_category(text):
    assert rule_category("out", text) == "tax"


def test_vat_phrase_is_not_a_tax_payment():
    # «Без налога (НДС)» в назначении закупки не делает её налогом — ловушка из EDA.
    assert rule_category("out", "Оплата по УПД № 5 от 01.02.2026. Без налога (НДС)") == "suppliers"


def test_software_abbreviation_is_case_sensitive():
    # «ПО» (программа) не должно матчить предлог «по» в любом назначении.
    assert rule_category("out", "Оплата по счету № 1 за товар") == "suppliers"
    assert rule_category("out", "Подписка на ПО за май") == "it_accounting"


def test_empty_purpose_filled_from_counterparty_history():
    ops = pd.DataFrame({
        "direction": ["out", "out", "out"], "cp_key": ["0022222222"] * 3,
        "payment_purpose": ["Оплата аренды за май", "Оплата аренды за июнь", ""],
    })
    out = categorize(ops)
    assert out.loc[2, "category"] == "rent"
    assert out.loc[2, "category_source"] == "counterparty"


def test_tax_deadline_moves_to_next_working_day():
    assert next_working_day(date(2026, 3, 28)) == date(2026, 3, 30)  # суббота → понедельник
    assert next_working_day(date(2026, 1, 3)) == date(2026, 1, 12)  # новогодние праздники
