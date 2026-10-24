"""Новая схема сохраняет прежние остатки, чеки и ключи повторной отправки."""
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.config import Settings
from app.db.models import BalancePoint, Company, ManualPaymentRequest, Operation, OperationAttachment, User
from app.db.session import Base


def test_balance_migration_preserves_old_data_and_refuses_lossy_downgrade(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "balances.db").as_posix()
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None, database_url=url, env="test"))
    config = Config("alembic.ini")
    command.upgrade(config, "c93d41ba620f")
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(User.__table__.insert().values(id="owner", login="saved", password_hash="hash"))
            conn.execute(Company.__table__.insert().values(id="company", owner_id="owner", external_id="C001", name="Saved"))
            for key, day, amount in [("bank", date(2026, 9, 1), "100.25"), ("manual:old", date(2026, 9, 2), "200.50")]:
                conn.execute(Operation.__table__.insert().values(id=key, company_id="company", source_operation_id=key,
                    op_date=day, amount=Decimal("100.25"), direction="in", counterparty_name="Клиент", purpose="Оплата",
                    balance_eod=Decimal(amount)))
            conn.execute(ManualPaymentRequest.__table__.insert().values(company_id="company", key="retry",
                         request_hash="a" * 64, operation_id="manual:old"))
            conn.execute(OperationAttachment.__table__.insert().values(id="receipt", operation_id="manual:old", kind="receipt",
                         filename="receipt.txt", content_type="text/plain", size_bytes=4, content=b"kept"))
        command.upgrade(config, "head")
        assert next(col for col in inspect(engine).get_columns("operations") if col["name"] == "balance_eod")["nullable"]
        with engine.connect() as conn:
            anchors = list(conn.execute(text("SELECT day, kind, amount FROM balance_points ORDER BY day")))
            assert [(str(day), kind, float(amount)) for day, kind, amount in anchors] == [
                ("2026-09-01", "statement", 100.25), ("2026-09-02", "legacy", 200.50)]
            assert conn.scalar(text("SELECT content FROM operation_attachments")) == b"kept"
            assert conn.scalar(text("SELECT operation_id FROM manual_payment_requests")) == "manual:old"
            assert float(conn.scalar(text("SELECT balance_eod FROM operations WHERE id = 'manual:old'"))) == 200.50
        with engine.begin() as conn:
            conn.execute(text("UPDATE operations SET balance_eod = NULL WHERE id = 'manual:old'"))
        with pytest.raises(RuntimeError, match="неизвестным остатком"):
            command.downgrade(config, "c93d41ba620f")
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "d184b62c9f30"
            assert conn.scalar(text("SELECT content FROM operation_attachments")) == b"kept"
        with engine.begin() as conn:
            conn.execute(text("UPDATE operations SET balance_eod = 200.50 WHERE id = 'manual:old'"))
        command.downgrade(config, "c93d41ba620f")
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM operations")) == 2
            assert conn.scalar(text("SELECT count(*) FROM balance_points")) == 2
            assert conn.scalar(text("SELECT content FROM operation_attachments")) == b"kept"
    finally:
        engine.dispose()


def test_adopting_new_dev_schema_does_not_freeze_calculated_balances(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "new-dev.db").as_posix()
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None, database_url=url, env="test"))
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(User.__table__.insert().values(id="owner", login="dev", password_hash="hash"))
            conn.execute(Company.__table__.insert().values(id="company", owner_id="owner", external_id="C001", name="Dev"))
            conn.execute(BalancePoint.__table__.insert().values(company_id="company", day=date(2026, 9, 1),
                         kind="initial", amount=Decimal(1000)))
            conn.execute(Operation.__table__.insert().values(id="op", company_id="company", source_operation_id="manual:op",
                         op_date=date(2026, 9, 2), amount=Decimal("100.25"), direction="in", counterparty_name="Клиент",
                         purpose="Оплата", balance_eod=Decimal("1100.25")))
        command.upgrade(Config("alembic.ini"), "head")
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM balance_points")) == 1
            assert conn.scalar(text("SELECT kind FROM balance_points")) == "initial"
            assert float(conn.scalar(text("SELECT balance_eod FROM operations"))) == 1100.25
    finally:
        engine.dispose()
