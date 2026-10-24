"""Публичные PDF, банковские остатки, изоляция счетов, ручной факт и план-факт."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.db.models import Company
from app.db.session import SessionLocal
from app.domain.ingest import StatementFormatError
from app.importers import parse_statement
from tests.test_api import _login

FIXTURES = Path(__file__).parent / "fixtures"
TXT = (FIXTURES / "client-bank.txt").read_text(encoding="utf-8")


def upload(client, headers, raw, filename="statement.txt", company_id=None):
    path = f"/api/companies/{company_id}/statements" if company_id else "/api/companies/import"
    return client.post(path, headers=headers, files={"file": (filename, raw)})


@pytest.mark.parametrize("encoding", ["utf-8-sig", "cp1251", "cp866"])
def test_client_bank_encodings_and_leading_zero_inn(encoding):
    frame = parse_statement(TXT.encode(encoding), "bank.txt").frame
    assert len(frame) == 2
    assert set(frame.counterparty_inn) == {"0011111111", "0022222222"}
    assert set(frame.balance_eod) == {1250}
    assert set(frame.direction) == {"in", "out"}


@pytest.mark.parametrize("original,replacement", [("1250.00", "1200.00"), ("КонецФайла", ""),
                                                  ("ДатаПоступило=01.09.2025", "ДатаПоступило="),
                                                  ("Сумма=500.00", "Сумма=-500.00"),
                                                  ("ВсегоПоступило=500.00", "ВсегоПоступило=500.001")])
def test_invalid_txt_is_rejected(original, replacement):
    with pytest.raises(StatementFormatError):
        parse_statement(TXT.replace(original, replacement).encode(), "bank.txt")


@pytest.mark.parametrize("name,count,amount,balance", [("incoming", 2, 395956.44, 395956.44),
                                                     ("outgoing", 1, 10009.52, 16457009.05)])
def test_real_bank_pdfs(name, count, amount, balance):
    frame = parse_statement((FIXTURES / f"raiffeisen-{name}.pdf").read_bytes(), "bank.pdf").frame
    assert len(frame) == count
    assert frame.amount.sum() == amount
    assert set(frame.balance_eod) == {balance}
    if name == "outgoing":
        assert frame.iloc[0].counterparty_name == "ООО Ромашка"
        assert frame.iloc[0].counterparty_inn == "6514008400"


def test_wrong_formats_return_safe_errors(client):
    headers = _login(client, "alice")
    for raw, name in [(b"", "empty.csv"), (b"hello", "bank.txt"), (b"%PDF-broken", "bank.pdf")]:
        assert upload(client, headers, raw, name).status_code == 422


def test_import_retries_overlapping_periods_and_accounts(client):
    headers = _login(client, "alice")
    initial = upload(client, headers, TXT.encode()).json()[0]
    cid = initial["company"]["id"]
    assert initial["rows_new"] == 2
    assert upload(client, headers, TXT.encode(), company_id=cid).json()[0]["already_imported"]
    # Иная кодировка и расширенный период сохраняют идентичность операций.
    extended = TXT.replace("ДатаКонца=01.09.2025", "ДатаКонца=02.09.2025")
    assert upload(client, headers, extended.encode("cp1251"), company_id=cid).json()[0]["rows_new"] == 0
    other = TXT.replace("40702810000000200000", "40702810000000200002")
    assert upload(client, headers, other.encode(), company_id=cid).status_code == 422
    assert len(client.get(f"/api/companies/{cid}/operations", headers=headers).json()) == 2
    second = client.post("/api/companies", headers=headers, json={"name": "Другая"}).json()["id"]
    assert upload(client, headers, TXT.encode(), company_id=second).status_code == 422
    assert client.get(f"/api/companies/{second}/operations", headers=headers).json() == []


def test_manual_payment_idempotency_balance_forecast_and_reconciliation(client):
    headers = _login(client, "alice")
    cid = client.post("/api/companies", headers=headers, json={"name": "Моя компания"}).json()["id"]
    assert client.get(f"/api/companies/{cid}/dashboard", headers=headers).status_code == 409
    planned = {"event_date": "2025-09-01", "amount": "500.25", "direction": "in", "title": "Клиент", "counterparty_key": "0011111111"}
    client.post(f"/api/companies/{cid}/events", headers=headers, json=planned)
    body = {"op_date": "2025-09-01", "amount": "500.25", "direction": "in", "counterparty_name": "ООО Клиент",
                "counterparty_inn": "0011111111", "purpose": "Оплата за товар", "balance_eod": "1500.25"}
    path, keyed = f"/api/companies/{cid}/operations", {**headers, "Idempotency-Key": "payment-1"}
    first = client.post(path, headers=keyed, json=body)
    assert first.status_code == 201, first.text
    assert first.json()["source"] == "manual" and first.json()["amount"] == "500.25"
    repeat = client.post(path, headers=keyed, json={**body, "amount": "500.250"})
    assert repeat.status_code == 200 and repeat.json()["id"] == first.json()["id"]
    assert client.post(path, headers=keyed, json={**body, "amount": "1"}).status_code == 409
    client.post(path, headers=headers, json={**body, "amount": "100", "direction": "out", "balance_eod": "1400.25"})
    assert {op["balance_eod"] for op in client.get(path, headers=headers).json()} == {"1400.25"}
    assert client.get(f"/api/companies/{cid}/events", headers=headers).json()[0]["status"] == "received"
    assert client.get(f"/api/companies/{cid}/dashboard", headers=headers).json()["forecast"]["last_balance"] == 1400.25
    with SessionLocal() as session:
        assert session.get(Company, cid).data_version == 2
    assert client.post(path, headers=_login(client, "bob"), json=body).status_code == 404
    for change in [{"amount": "0"}, {"amount": "1.001"}, {"counterparty_inn": "123"},
                   {"owner_id": "other"}, {"op_date": str(date.today() + timedelta(days=1))}]:
        assert client.post(path, headers=headers, json={**body, **change}).status_code == 422
