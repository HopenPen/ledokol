"""Сквозной пайплайн для одной компании: выписка → качество → категории → модель. Используется API, CLI и бэктестом."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.domain.categorize import TextClassifier, categorize
from app.domain.ingest import QualityReport, flag_quality


@dataclass(slots=True)
class PreparedCompany:
    company_id: str
    ops: pd.DataFrame        # категоризированные, с пометками качества
    panel: pd.DataFrame      # дневной остаток на рабочих днях
    quality: QualityReport


def prepare_company(ops: pd.DataFrame, classifier: TextClassifier | None = None) -> PreparedCompany:
    company_ids = ops["company_id"].unique()
    if len(company_ids) != 1:
        raise ValueError("prepare_company ожидает операции одной компании")
    known = ops[ops["balance_eod"].notna()]
    flagged, panel, rep = flag_quality(known)
    unknown = ops[ops["balance_eod"].isna()]
    if not unknown.empty:
        flagged = pd.concat([flagged, unknown.assign(quality="ok")]).sort_values(
            ["operation_date", "operation_id"])
        rep.rows_total = len(ops)
        rep.empty_purpose = int(ops["payment_purpose"].eq("").sum())
        rep.empty_inn = int(ops["counterparty_inn"].eq("").sum())
        rep.warnings.append(f"У {len(unknown)} операций неизвестен остаток. Укажите начальный остаток в «Источниках»; "
                            "пока эти операции не участвуют в прогнозе.")
    return PreparedCompany(str(company_ids[0]), categorize(flagged, classifier), panel, rep)


def split_by_company(ops: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {str(cid): g.reset_index(drop=True) for cid, g in ops.groupby("company_id", sort=True)}
