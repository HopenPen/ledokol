"""Проведённые платежи, опорные остатки, сверка выписки и сохранность карточек."""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import BalancePoint, Company, Operation
from app.db.session import SessionLocal
from app.domain.balances import BalanceError, Point, daily_balances
from tests.test_api import _login
from tests.test_import_acceptance import row, statement


@pytest.fixture
def account(client):
    headers = _login(client, "alice")
    cid = client.post("/api/companies", headers=headers, json={"name": "Расчёт остатков"}).json()["id"]
    return client, headers, f"/api/companies/{cid}"


def payment(account, day="2026-09-01", amount="100.25", direction="in", key=None, **changes):
    client, headers, path = account
    body = {"op_date": day, "amount": amount, "direction": direction,
            "counterparty_name": "Клиент", "counterparty_inn": "0011111111", "purpose": "Оплата по счёту 1", **changes}
    return client.post(path + "/operations", headers={**headers, **({"Idempotency-Key": key} if key else {})}, json=body)


def initial(account, amount="1000.00", day="2026-09-01"):
    client, headers, path = account
    return client.put(path + "/balance/initial", headers=headers, json={"date": day, "amount": amount})


def upload(account, rows):
    client, headers, path = account
    return client.post(path + "/statements", headers=headers, files={"file": ("bank.csv", statement(rows), "text/csv")})


def bank_row(**changes):
    return row(**{"company_id": "BASIC", "operation_date": "2026-09-01", "amount": "100.25", "direction": "Поступление",
                  "counterparty_name": "Клиент", "payment_purpose": "Оплата по счёту 1", "balance_eod": "1100.25", **changes})


def test_unknown_balance_saves_actuals_and_matches_events_without_fake_forecast(account):
    client, headers, path = account
    client.post(path + "/events", headers=headers, json={"event_date": "2026-09-01", "amount": "100.25",
                "direction": "in", "title": "Оплата", "counterparty_key": "0011111111"})
    saved = payment(account, key="retry")
    assert saved.status_code == 201, saved.text
    assert saved.json()["balance_eod"] is None
    assert payment(account, key="retry").status_code == 200
    assert client.get(path + "/balance", headers=headers).json()["source"] == "unknown"
    assert client.get(path + "/events", headers=headers).json()[0]["status"] == "received"
    for endpoint in ["/dashboard", "/forecast", "/plan-fact", "/plan-fact/daily"]:
        assert client.get(path + endpoint, headers=headers).status_code == 409
    for endpoint in ["/scenarios", "/forecast/preview"]:
        assert client.post(path + endpoint, headers=headers, json={}).status_code == 409
    assert client.post(path + "/assistant/ask", headers=headers, json={"question": "Сколько денег?"}).status_code == 409
    assert initial(account).status_code == 200
    forecast = client.get(path + "/dashboard", headers=headers).json()["forecast"]
    assert forecast["last_balance"] == 1100.25 and forecast["as_of"] == "2026-09-01"
    assert client.get(path + "/balance", headers=headers).json()["unknown_operations"] == 0


def test_backdated_and_same_day_payments_recalculate_with_kopecks(account):
    client, headers, path = account
    assert initial(account).json()["source"] == "initial"
    assert payment(account, day="2026-09-03", amount="200.10").json()["balance_eod"] == "1200.10"
    assert payment(account, day="2026-09-01", amount="50.01", direction="out").json()["balance_eod"] == "949.99"
    assert payment(account, day="2026-09-01", amount="10.02").json()["balance_eod"] == "960.01"
    operations = client.get(path + "/operations", headers=headers).json()
    assert [op["balance_eod"] for op in operations] == ["1160.11", "960.01", "960.01"]
    assert client.get(path + "/balance", headers=headers).json()["source"] == "calculated"
    before = client.get(path + "/dashboard", headers=headers).json()["forecast"]
    client.post(path + "/events", headers=headers, json={"event_date": "2026-09-04", "amount": "200",
                "direction": "out", "title": "Ожидаемая оплата"})
    after = client.get(path + "/dashboard", headers=headers).json()["forecast"]
    assert before["last_balance"] == after["last_balance"] == 1160.11
    # Смена начальной суммы сбрасывает кеш модели, повтор того же PUT — no-op.
    assert initial(account, amount="2000").json()["amount"] == "2160.11"
    with SessionLocal() as session:
        version = session.get(Company, path.rsplit("/", 1)[1]).data_version
    assert initial(account, amount="2000").status_code == 200
    with SessionLocal() as session:
        assert session.get(Company, path.rsplit("/", 1)[1]).data_version == version
    assert client.get(path + "/forecast", headers=headers).json()["last_balance"] == 2160.11


@pytest.mark.parametrize("amount", ["0", "-50.25"])
def test_zero_and_negative_initial_balance_are_known(account, amount):
    client, headers, path = account
    assert initial(account, amount=amount).status_code == 200
    assert payment(account).json()["balance_eod"] == f"{Decimal(amount) + Decimal('100.25'):.2f}"
    assert client.get(path + "/forecast", headers=headers).status_code == 200


def test_initial_balance_validation_ownership_and_earlier_payments(account):
    client, headers, path = account
    assert initial(account).status_code == 200
    assert payment(account, day="2026-08-31").status_code == 422
    assert client.get(path + "/operations", headers=headers).json() == []
    assert payment(account).status_code == 201
    for body in [{"date": "2026-09-02", "amount": "1"}, {"date": "2026-09-01", "amount": "1.001"},
                 {"date": str(date.today() + timedelta(days=1)), "amount": "1"},
                 {"date": "2026-09-01", "amount": "NaN"}]:
        assert client.put(path + "/balance/initial", headers=headers, json=body).status_code == 422
    other = _login(client, "bob")
    assert client.get(path + "/balance", headers=other).status_code == 404
    assert client.put(path + "/balance/initial", headers=other, json={"date": "2026-09-01", "amount": "1"}).status_code == 404
    assert client.get(path + "/balance").status_code == 401


@pytest.mark.parametrize("manual_inn", ["", "0011111111"])
def test_statement_confirms_manual_payment_preserving_id_category_files_and_retry(account, manual_inn):
    client, headers, path = account
    initial(account)
    saved = payment(account, key="keep-id", counterparty_inn=manual_inn).json()
    op_id = saved["id"]
    client.patch(f"/api/operations/{op_id}/category", headers=headers,
                 json={"category": "suppliers", "apply_to_counterparty": False})
    receipt = client.post(f"/api/operations/{op_id}/attachments", headers=headers,
                          data={"kind": "receipt"}, files={"files": ("receipt.txt", b"Receipt", "text/plain")})
    assert receipt.status_code == 201, receipt.text
    imported = upload(account, [bank_row()])
    assert imported.status_code == 200, imported.text
    assert imported.json()[0]["rows_new"] == 0 and imported.json()[0]["rows_matched"] == 1
    actual = client.get(path + "/operations", headers=headers).json()
    assert len(actual) == 1 and actual[0]["id"] == op_id and actual[0]["source"] == "statement"
    assert actual[0]["category_source"] == "user" and actual[0]["category"] == "suppliers"
    assert client.get(f"/api/operations/{op_id}/attachments", headers=headers).json()[0]["id"] == receipt.json()[0]["id"]
    retry = payment(account, key="keep-id", counterparty_inn=manual_inn)
    assert retry.status_code == 200 and retry.json()["id"] == op_id
    assert upload(account, [bank_row()]).json()[0]["already_imported"]
    assert client.get(path + "/forecast", headers=headers).json()["last_balance"] == 1100.25
    assert client.get(path + "/balance", headers=headers).json()["source"] == "statement"


def test_bank_anchor_is_authoritative_and_does_not_count_same_day_payments_twice(account):
    client, headers, path = account
    initial(account)
    payment(account)
    payment(account, day="2026-09-03", amount="25.05", direction="out")
    assert upload(account, [bank_row()]).status_code == 200
    assert payment(account, amount="5", direction="out").json()["balance_eod"] == "1100.25"
    assert payment(account, day="2026-09-02", amount="10.01").status_code == 201
    assert client.get(path + "/balance", headers=headers).json()["amount"] == "1085.21"
    with SessionLocal() as session:
        point = session.get(BalancePoint, (path.rsplit("/", 1)[1], date(2026, 9, 1), "statement"))
        assert point.amount == Decimal("1100.25")
    assert initial(account, amount="5000").json()["amount"] == "1085.21"
    assert client.get(path + "/forecast", headers=headers).json()["last_balance"] == 1085.21


def test_bank_only_history_and_earlier_unknown_payments(account):
    client, headers, path = account
    assert upload(account, [bank_row()]).status_code == 200
    assert payment(account, day="2026-08-28", amount="50").json()["balance_eod"] is None
    assert client.get(path + "/balance", headers=headers).json()["unknown_operations"] == 1
    forecast = client.get(path + "/forecast", headers=headers).json()
    assert forecast["last_balance"] == 1100.25
    assert any("неизвестен остаток" in warning for warning in forecast["warnings"])
    assert initial(account, day="2026-08-28", amount="1000").json()["unknown_operations"] == 0
    assert client.get(path + "/forecast", headers=headers).json()["last_balance"] == 1100.25


def test_ambiguous_reconciliation_is_atomic(account):
    client, headers, path = account
    initial(account)
    payment(account)
    payment(account)
    response = upload(account, [bank_row()])
    assert response.status_code == 422
    assert "несколько одинаковых" in response.json()["detail"]
    operations = client.get(path + "/operations", headers=headers).json()
    assert len(operations) == 2 and all(op["source"] == "manual" for op in operations)
    assert client.get(path + "/balance", headers=headers).json()["amount"] == "1200.50"
    with SessionLocal() as session:
        assert not session.scalars(select(BalancePoint).where(BalancePoint.kind == "statement")).all()
        assert len(session.scalars(select(Operation)).all()) == 2


def test_projection_uses_bank_anchor_instead_of_later_initial_point():
    day = date(2026, 9, 1)
    later = day + timedelta(days=1)
    assert daily_balances({later: Decimal("0.01")}, [Point(day, Decimal(100), "statement"),
                                                   Point(later, Decimal(999), "initial")])[later] == Decimal("100.01")
    with pytest.raises(BalanceError):
        daily_balances({day: Decimal("0.01")}, [Point(day, Decimal("99999999999999.99"), "initial")])


def test_balance_overflow_rolls_back_payment(account):
    client, headers, path = account
    assert initial(account, amount="99999999999999.00").status_code == 200
    response = payment(account, amount="1.00")
    assert response.status_code == 422
    assert client.get(path + "/operations", headers=headers).json() == []
    assert client.get(path + "/balance", headers=headers).json()["amount"] == "99999999999999.00"
