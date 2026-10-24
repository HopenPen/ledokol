"""Новая миграция сохраняет данные уже установленной версии."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.core.config import get_settings


def test_attachment_upgrade_preserves_existing_users(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "migration.db"}'
    monkeypatch.setenv('CASHFLOW_DATABASE_URL', url)
    get_settings.cache_clear()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / 'alembic.ini'))
    config.set_main_option('script_location', str(root / 'migrations'))
    engine = create_engine(url)
    try:
        command.upgrade(config, 'b872c30a951e')
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, login, password_hash) VALUES ('kept', 'owner', 'hash')"))
        command.upgrade(config, 'head')
        assert 'operation_attachments' in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT login FROM users WHERE id = \'kept\'')) == 'owner'
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()
        command.downgrade(config, 'b872c30a951e')
        command.upgrade(config, 'head')
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT count(*) FROM users')) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()
