"""Новая миграция сохраняет существующих пользователей и компании."""
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.core.config import Settings
from app.db.models import (
    BankAccount,
    Company,
    ManualPaymentRequest,
    Operation,
    PlannedEvent,
    StatementImport,
    User,
)
from app.db.session import Base


def test_upgrade_existing_database_and_downgrade(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "migration.db").as_posix()
    settings = Settings(_env_file=None, database_url=url, env="test")
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    config = Config("alembic.ini")
    command.upgrade(config, "a51c3667275f")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, login, password_hash) VALUES ('old', 'legacy', 'hash')"))
    command.upgrade(config, "head")
    assert {"bank_accounts", "manual_payment_requests", "user_emails"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT login FROM users WHERE id='old'")) == "legacy"
    command.downgrade(config, "a51c3667275f")
    assert "user_emails" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    engine.dispose()


@pytest.mark.parametrize("old_payments", [False, True])
def test_adopt_create_all_database_without_migration_history(tmp_path, monkeypatch, old_payments):
    url = "sqlite:///" + (tmp_path / "legacy.db").as_posix()
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None, database_url=url, env="test"))
    engine = create_engine(url)
    tables = [User.__table__, Company.__table__, Operation.__table__, PlannedEvent.__table__, StatementImport.__table__]
    if old_payments:
        tables += [BankAccount.__table__, ManualPaymentRequest.__table__]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(User.__table__.insert().values(id="old", login="legacy", password_hash="saved-hash"))
        connection.execute(Company.__table__.insert().values(id="company", owner_id="old", external_id="C001", name="Legacy"))
        connection.execute(text("INSERT INTO operations (id, company_id, source_operation_id, op_date, amount, direction, "
                                "counterparty_name, purpose, balance_eod, category, category_source, confidence, quality) "
                                "VALUES ('op', 'company', 'manual:old', '2025-09-01', 1.25, 'in', 'Client', 'Payment', "
                                "101.25, 'unknown', 'none', 0, 'ok')"))
        if old_payments:
            connection.execute(BankAccount.__table__.insert().values(company_id="company", owner_id="old", number="40702810000000200000"))
            connection.execute(ManualPaymentRequest.__table__.insert().values(company_id="company", key="old-key", request_hash="a" * 64, operation_id="op"))
            connection.execute(text('ALTER TABLE manual_payment_requests RENAME COLUMN "key" TO idempotency_key'))
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # повторный запуск обычный, без повторной миграции и переименования
    assert {"user_emails", "forecast_runs", "forecast_points"}.issubset(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ScriptDirectory.from_config(config).get_current_head()
        assert connection.scalar(text("SELECT password_hash FROM users WHERE id='old'")) == "saved-hash"
        assert connection.scalar(text("SELECT name FROM companies WHERE id='company'")) == "Legacy"
        assert float(connection.scalar(text("SELECT amount FROM operations WHERE id='op'"))) == 1.25
        if old_payments:
            assert connection.scalar(text('SELECT "key" FROM manual_payment_requests')) == "old-key"
    engine.dispose()


def test_incompatible_legacy_schema_is_not_stamped(tmp_path, monkeypatch):
    url = "sqlite:///" + (tmp_path / "incompatible.db").as_posix()
    monkeypatch.setattr("app.core.config.get_settings", lambda: Settings(_env_file=None, database_url=url, env="test"))
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, unexpected TEXT)"))
        connection.execute(text("INSERT INTO users VALUES ('keep', 'saved')"))
    with pytest.raises(RuntimeError, match="users"):
        command.upgrade(Config("alembic.ini"), "head")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT unexpected FROM users")) == "saved"
        assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    engine.dispose()
