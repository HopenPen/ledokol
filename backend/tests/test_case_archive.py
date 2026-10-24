"""Приёмка исходного архива кейса без хранения датасета в репозитории и без ML."""
import os
import zipfile

import pandas as pd
import pytest

from app.domain.ingest import REQUIRED_COLUMNS, flag_quality, read_statement


@pytest.mark.skipif(not os.environ.get("CASHFLOW_ACCEPTANCE_ARCHIVE"), reason="Нужен исходный архив кейса")
def test_all_case_statements_import_through_authenticated_api(client):
    from sqlalchemy import func, select

    from app.db.models import Operation
    from app.db.session import SessionLocal
    from tests.test_api import _login

    headers = _login(client, "alice")
    total = 0
    with zipfile.ZipFile(os.environ["CASHFLOW_ACCEPTANCE_ARCHIVE"]) as archive:
        files = sorted(n for n in archive.namelist() if n.startswith("statements/") and n.endswith(".csv"))
        assert len(files) == 150
        for name in files:
            response = client.post("/api/companies/import", headers=headers,
                                   files={"file": ("statement.csv", archive.read(name), "text/csv")})
            assert response.status_code == 201, name + ": " + response.text[:300]
            result = response.json()[0]
            assert result["quality"]["rows_rejected"] == 0
            total += result["rows_new"]
        repeated = client.post("/api/companies/import", headers=headers,
                               files={"file": ("statement.csv", archive.read(files[0]), "text/csv")})
        assert repeated.status_code == 201 and repeated.json()[0]["rows_new"] == 0
    assert total == 222420
    assert len(client.get("/api/companies", headers=headers).json()) == 150
    with SessionLocal() as session:
        assert session.scalar(select(func.count()).select_from(Operation)) == total
        assert session.scalar(select(func.count()).select_from(Operation).where(Operation.quality == "duplicate")) == 20


@pytest.mark.skipif(not os.environ.get("CASHFLOW_ACCEPTANCE_ARCHIVE"), reason="Нужен исходный архив кейса")
def test_all_case_statements_match_combined_file_and_find_twenty_duplicates():
    with zipfile.ZipFile(os.environ["CASHFLOW_ACCEPTANCE_ARCHIVE"]) as archive:
        files = sorted(name for name in archive.namelist() if name.startswith("statements/") and name.endswith(".csv"))
        assert len(files) == 150
        combined = read_statement(archive.read("all_operations.csv"))
        assert combined.attrs["rows_rejected"] == 0
        total, duplicates, leading_zeros = 0, 0, 0
        for name in files:
            frame = read_statement(archive.read(name))
            assert frame.attrs["rows_rejected"] == 0
            assert frame["company_id"].nunique() == 1
            part = combined[combined["company_id"].eq(frame["company_id"].iloc[0])]
            pd.testing.assert_frame_equal(frame[REQUIRED_COLUMNS].reset_index(drop=True),
                                          part[REQUIRED_COLUMNS].reset_index(drop=True))
            _, panel, quality = flag_quality(frame)
            assert not panel.empty and panel["balance"].notna().all()
            total += len(frame)
            duplicates += quality.duplicates
            leading_zeros += int(frame["counterparty_inn"].str.startswith("00").sum())
        assert total == len(combined)
        assert duplicates == 20
        assert leading_zeros > 0
        print(f"Приёмка: компаний={len(files)}, операций={total}, дублей={duplicates}, ИНН с нулями={leading_zeros}")
