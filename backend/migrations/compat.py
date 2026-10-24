"""Принятие совместимых таблиц, созданных create_all до появления Alembic.

Проверяем схему перед пропуском CREATE TABLE. Версию записывает сам Alembic после
успешной миграции; чужая или неполная таблица не получает фиктивный stamp head.
"""
import sqlalchemy as sa
from alembic import op


def create_table(name, *elements, column_renames=None):
    if op.get_context().as_sql:
        return op.create_table(name, *elements)
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(name):
        return op.create_table(name, *elements)

    expected = sa.Table(name, sa.MetaData(), *elements)
    existing = {column["name"]: column for column in inspector.get_columns(name)}
    renames = {old: new for old, new in (column_renames or {}).items() if old in existing and new not in existing}
    normalized = {renames.get(key, key): value for key, value in existing.items()}

    def require(condition, part):
        if not condition:
            raise RuntimeError(f"Несовместимая старая таблица {name}: {part}. Миграция остановлена; данные не удалены.")

    require(set(normalized) == set(expected.columns.keys()), "набор колонок")
    for column in expected.columns:
        actual = normalized[column.name]
        require(_same_type(column.type, actual["type"], inspector.bind.dialect.name), f"тип {column.name}")
        widened_balance = name == "operations" and column.name == "balance_eod" and actual["nullable"]
        require(column.nullable == actual["nullable"] or widened_balance, f"nullable {column.name}")
    def rename_columns(columns):
        return tuple(renames.get(col, col) for col in columns)

    require(rename_columns(inspector.get_pk_constraint(name)["constrained_columns"]) == tuple(expected.primary_key.columns.keys()),
            "первичный ключ")
    unique = {frozenset(rename_columns(item["column_names"])) for item in inspector.get_unique_constraints(name)}
    for constraint in expected.constraints:
        if isinstance(constraint, sa.UniqueConstraint):
            require(frozenset(constraint.columns.keys()) in unique, "уникальность " + ", ".join(constraint.columns.keys()))
        elif isinstance(constraint, sa.ForeignKeyConstraint):
            elements = list(constraint.elements)
            target_table = elements[0].target_fullname.rsplit(".", 1)[0]
            target_columns = tuple(item.target_fullname.rsplit(".", 1)[1] for item in elements)
            require(any(rename_columns(fk["constrained_columns"]) == tuple(constraint.columns.keys())
                        and fk["referred_table"] == target_table and tuple(fk["referred_columns"]) == target_columns
                        and fk.get("options", {}).get("ondelete") == constraint.ondelete
                        for fk in inspector.get_foreign_keys(name)), "внешний ключ")
        elif isinstance(constraint, sa.CheckConstraint) and constraint.name:
            require(constraint.name in {check["name"] for check in inspector.get_check_constraints(name)},
                    f"ограничение {constraint.name}")
    # Известное старое имя колонки меняем только после проверки всей таблицы.
    for old, new in renames.items():
        op.alter_column(name, old, new_column_name=new)
    return None


def _same_type(expected, actual, dialect):
    if isinstance(expected, sa.String):
        return isinstance(actual, sa.String) and expected.length == actual.length
    if isinstance(expected, sa.Numeric):
        return isinstance(actual, sa.Numeric) and (expected.precision, expected.scale) == (actual.precision, actual.scale)
    if isinstance(expected, sa.DateTime):
        return isinstance(actual, sa.DateTime) and (dialect != "postgresql" or expected.timezone == actual.timezone)
    return isinstance(actual, type(expected.as_generic()))
