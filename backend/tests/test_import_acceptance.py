"""Минимум кейса: плохие строки объясняются, хорошие операции сохраняются."""
import csv
import io

import pytest

from app.domain.ingest import REQUIRED_COLUMNS
from tests.test_api import _login


def statement(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=REQUIRED_COLUMNS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


def row(**changes):
    return {**dict(zip(REQUIRED_COLUMNS, ["BASIC", "op-1", "2026-10-23", "125.50", "Списание",
                                        "0011111111", "Закрытое имя", "Секретное назначение", "-125.50"])), **changes}


@pytest.mark.parametrize("change", [
    {"direction": "неизвестно"}, {"counterparty_inn": "abc"}, {"amount": "inf"},
    {"balance_eod": "-inf"}, {"operation_date": "2026-02-30"}, {"operation_id": ""},
])
def test_invalid_csv_row_reports_line_without_leaking_values(client, change):
    bad = row(operation_id="op-2", **change) if "operation_id" not in change else row(**change)
    response = client.post("/api/companies/import", headers=_login(client, "alice"),
                           files={"file": ("statement.csv", statement([row(), bad]), "text/csv")})
    assert response.status_code == 201, response.text
    result = response.json()[0]
    assert result["rows_new"] == 1
    assert result["quality"]["rows_rejected"] == 1
    warnings = " ".join(result["quality"]["warnings"])
    assert "3" in warnings and "строк" in warnings
    assert next(iter(change)) in warnings
    assert "Закрытое имя" not in warnings and "Секретное назначение" not in warnings


@pytest.mark.parametrize("raw", [b"", b"\xff\xfe\x00\x81", statement([]),
                                   statement([row(direction="неизвестно")])])
def test_unusable_csv_is_safe_and_atomic(client, raw):
    headers = _login(client, "alice")
    response = client.post("/api/companies/import", headers=headers,
                           files={"file": ("broken.csv", raw, "text/csv")})
    assert response.status_code == 422
    assert client.get("/api/companies", headers=headers).json() == []


def test_one_outgoing_operation_preserves_inn_and_produces_dashboard(client):
    headers = _login(client, "alice")
    response = client.post("/api/companies/import", headers=headers,
                           files={"file": ("single.csv", statement([row()]), "text/csv")})
    assert response.status_code == 201
    cid = response.json()[0]["company"]["id"]
    operations = client.get(f"/api/companies/{cid}/operations", headers=headers).json()
    assert len(operations) == 1 and operations[0]["counterparty_inn"] == "0011111111"
    dashboard = client.get(f"/api/companies/{cid}/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert len(dashboard.json()["forecast"]["points"]) == 30
