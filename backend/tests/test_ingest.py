from __future__ import annotations

import pandas as pd
import pytest

from app.domain.ingest import StatementFormatError, flag_quality, read_statement
from tests.conftest import make_company, to_case_csv


def test_inn_keeps_leading_zeros():
    df = read_statement(to_case_csv(make_company(days=20)))
    assert df["counterparty_inn"].str.startswith("00").any()
    assert df["counterparty_inn"].str.len().isin([0, 10, 12]).all()


def test_rejects_file_without_required_columns():
    with pytest.raises(StatementFormatError):
        read_statement("a;b\n1;2".encode("utf-8-sig"))


def test_duplicate_not_in_balance_is_flagged(company_ops):
    # Дублируем строку, НЕ меняя остаток дня: так выглядит артефакт выгрузки из EDA.
    dup = company_ops.iloc[[10]].assign(operation_id="T001-DUP")
    ops = pd.concat([company_ops, dup], ignore_index=True)
    flagged, _, rep = flag_quality(ops)
    assert rep.duplicates == 1
    assert flagged.loc[flagged["operation_id"].isin(["T001-DUP", company_ops.iloc[10]["operation_id"]]), "quality"] \
        .eq("duplicate").sum() == 1


def test_identical_real_payments_are_not_flagged(company_ops):
    # Две одинаковые реальные оплаты в один день, обе учтены в остатке → это не дубль.
    row = company_ops.iloc[[10]].copy()
    day = row["operation_date"].iloc[0]
    ops = company_ops.copy()
    ops.loc[ops["operation_date"].ge(day), "balance_eod"] += row["signed"].iloc[0]
    ops = pd.concat([ops, row.assign(operation_id="T001-REAL")], ignore_index=True)
    _, _, rep = flag_quality(ops)
    assert rep.duplicates == 0


def test_gap_with_balance_jump_is_marked(company_ops):
    days = sorted(company_ops["operation_date"].unique())
    hole = days[50:58]                       # 8 рабочих дней пропали из выгрузки
    ops = company_ops[~company_ops["operation_date"].isin(hole)]
    _, panel, rep = flag_quality(ops)
    assert rep.balance_jumps >= 1
    assert panel["after_gap"].any()
