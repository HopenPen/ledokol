"""Удаление владельцем: все связи, файлы и прогнозы исчезают, другие компании сохраняются."""
from datetime import date
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    BalancePoint,
    BankAccount,
    Company,
    ForecastPointRow,
    ForecastRun,
    ManualPaymentRequest,
    Operation,
    OperationAttachment,
    PlannedEvent,
    StatementImport,
    User,
)
from app.db.session import SessionLocal
from app.services.companies import delete_company
from app.services.forecasting import _cache, company_model
from tests.test_api import _login

RELATED = (Company, BankAccount, StatementImport, BalancePoint, Operation, ManualPaymentRequest,
           OperationAttachment, PlannedEvent, ForecastRun, ForecastPointRow)


def counts(session):
    return {model.__tablename__: session.scalar(select(func.count()).select_from(model)) for model in RELATED}


def populated_company(session, owner, external, account):
    company = Company(owner_id=owner.id, external_id=external, name=external)
    session.add(company)
    session.flush()
    session.add_all([
        BankAccount(company_id=company.id, owner_id=owner.id, number=account),
        StatementImport(company_id=company.id, sha256="a" * 64, rows_total=1, rows_new=1),
        BalancePoint(company_id=company.id, day=date(2026, 9, 1), kind="initial", amount=Decimal(1000)),
        BalancePoint(company_id=company.id, day=date(2026, 9, 1), kind="statement", amount=Decimal("1125.50")),
        BalancePoint(company_id=company.id, day=date(2026, 8, 31), kind="legacy", amount=Decimal(1000)),
        *[PlannedEvent(company_id=company.id, event_date=date(2026, 9, 3), amount=Decimal(10),
                       direction="out", kind="manual", source=source, title="Expected payment")
          for source in ("manual", "1c", "fns")],
    ])
    operations = [Operation(company_id=company.id, source_operation_id=source, op_date=day,
                            amount=Decimal(amount), direction=direction, counterparty_name="Client",
                            purpose="Оплата по счёту", balance_eod=Decimal(balance))
                  for source, day, amount, direction, balance in [
                      ("bank:1", date(2026, 9, 1), "125.50", "in", "1125.50"),
                      ("manual:1", date(2026, 9, 2), "25.50", "out", "1100.00")]]
    run = ForecastRun(company_id=company.id, as_of=date(2026, 9, 2), data_version=0,
                      events_hash="b" * 64, model_version="test", horizon=30)
    session.add_all([*operations, run])
    session.flush()
    attachments = [OperationAttachment(operation_id=operation.id, kind=kind, filename="document.txt",
                                       content_type="text/plain", size_bytes=6, content=b"secret")
                   for operation, kind in zip(operations, ("receipt", "related"))]
    session.add_all([
        *attachments,
        ManualPaymentRequest(company_id=company.id, key="retry", request_hash="c" * 64, operation_id=operations[1].id),
        ForecastPointRow(run_id=run.id, day=date(2026, 9, 3), p10=Decimal(1000), p50=Decimal(1100), p90=Decimal(1200)),
    ])
    session.flush()
    return company, operations, attachments


def test_owner_deletion_cascades_all_data_keeps_other_companies_and_allows_reimport(client):
    headers = _login(client, "alice")
    with SessionLocal() as session:
        alice = session.scalar(select(User).where(User.login == "alice"))
        bob = session.scalar(select(User).where(User.login == "bob"))
        kept, _, _ = populated_company(session, alice, "KEEP", "40702810000000200001")
        populated_company(session, bob, "OTHER", "40702810000000200002")
        session.commit()
        protected = counts(session)
        target, operations, attachments = populated_company(session, alice, "DELETE", "40702810000000200000")
        session.commit()
        cid, kept_id = target.id, kept.id
        operation_id, attachment_id = operations[0].id, attachments[0].id
        company_model(session, target)
        kept_model = company_model(session, kept)
        assert _cache.get((cid, 0)) is not None
    response = client.delete(f"/api/companies/{cid}", headers=headers)
    assert response.status_code == 204 and response.content == b""
    with SessionLocal() as session:
        assert counts(session) == protected
        assert session.scalar(select(func.count()).select_from(User)) == 2
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert _cache.get((cid, 0)) is None and _cache.get((kept_id, 0)) is kept_model
    assert client.get(f"/api/companies/{cid}", headers=headers).status_code == 404
    assert client.get(f"/api/operations/{operation_id}/attachments", headers=headers).status_code == 404
    assert client.get(f"/api/attachments/{attachment_id}/file", headers=headers).status_code == 404
    assert [item["id"] for item in client.get("/api/companies", headers=headers).json()] == [kept_id]
    raw = (Path(__file__).parent / "fixtures/client-bank.txt").read_bytes()
    imported = client.post("/api/companies/import", headers=headers, files={"file": ("bank.txt", raw)})
    assert imported.status_code == 201, imported.text
    result = imported.json()[0]
    assert result["company"]["id"] != cid and result["rows_new"] == 2 and not result["already_imported"]


def test_delete_requires_owner_and_supports_empty_company(client):
    headers = _login(client, "alice")
    company = client.post("/api/companies", headers=headers, json={"name": "Empty company"}).json()
    path = f"/api/companies/{company['id']}"
    assert client.delete(path).status_code == 401
    assert client.delete(path, headers=_login(client, "bob")).status_code == 404
    assert client.get(path, headers=headers).status_code == 200
    assert client.delete("/api/companies/missing", headers=headers).status_code == 404
    assert client.delete(path, headers=headers).status_code == 204
    assert client.delete(path, headers=headers).status_code == 404
    assert client.get("/api/companies", headers=headers).json() == []


def test_company_deletion_on_migrated_schema_with_loaded_operations(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "company-deletion.db").as_posix()
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None, database_url=url, env="test"))
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    try:
        with Session(engine, expire_on_commit=False) as session:
            owner = User(login="owner", password_hash="hash")
            session.add(owner)
            session.flush()
            populated_company(session, owner, "KEEP", "40702810000000200001")
            session.commit()
            protected = counts(session)
            target, _, _ = populated_company(session, owner, "DELETE", "40702810000000200000")
            session.commit()
            assert len(target.operations) == 2
            delete_company(session, target)
            assert counts(session) == protected
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    finally:
        engine.dispose()
