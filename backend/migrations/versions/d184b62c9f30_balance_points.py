"""Separate balance anchors from calculated payment balances.

Revision ID: d184b62c9f30
Revises: c93d41ba620f
"""
import sqlalchemy as sa
from alembic import op

from migrations.compat import create_table

revision = "d184b62c9f30"
down_revision = "c93d41ba620f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dev может уже работать на новой схеме через create_all. Его рассчитанные
    # остатки нельзя превращать в дополнительные опорные суммы при принятии Alembic.
    already_calculated = False
    if not op.get_context().as_sql:
        inspector = sa.inspect(op.get_bind())
        already_calculated = inspector.has_table("balance_points") and any(
            col["name"] == "balance_eod" and col["nullable"] for col in inspector.get_columns("operations"))
    create_table("balance_points",
                 sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
                 sa.Column("day", sa.Date(), primary_key=True),
                 sa.Column("kind", sa.Enum("initial", "statement", "legacy", name="balance_kind", native_enum=False,
                                           create_constraint=True, length=9), primary_key=True),
                 sa.Column("amount", sa.Numeric(16, 2), nullable=False))
    op.create_index("uq_company_initial_balance", "balance_points", ["company_id"], unique=True,
                    sqlite_where=sa.text("kind = 'initial'"), postgresql_where=sa.text("kind = 'initial'"), if_not_exists=True)
    # Старый ручной ввод мог перезаписать остаток всего дня. Сохраняем сумму,
    # но не выдаём её за подтверждённую банком.
    if not already_calculated:
        op.execute(sa.text("""
        INSERT INTO balance_points (company_id, day, kind, amount)
        SELECT o.company_id, o.op_date,
               CASE WHEN EXISTS (
                   SELECT 1 FROM operations m WHERE m.company_id = o.company_id
                       AND m.op_date = o.op_date AND m.source_operation_id LIKE 'manual:%'
               ) THEN 'legacy' ELSE 'statement' END,
               o.balance_eod
        FROM operations o
        WHERE o.balance_eod IS NOT NULL
          AND o.source_operation_id = (
              SELECT MIN(m.source_operation_id) FROM operations m
              WHERE m.company_id = o.company_id AND m.op_date = o.op_date AND m.balance_eod IS NOT NULL
          )
          AND NOT EXISTS (SELECT 1 FROM balance_points b WHERE b.company_id = o.company_id AND b.day = o.op_date)
        """))
    with op.batch_alter_table("operations") as batch:
        batch.alter_column("balance_eod", existing_type=sa.Numeric(16, 2), nullable=True)


def downgrade() -> None:
    if not op.get_context().as_sql and op.get_bind().scalar(sa.text(
            "SELECT count(*) FROM operations WHERE balance_eod IS NULL")):
        raise RuntimeError("Перед откатом укажите начальные остатки: есть операции с неизвестным остатком. Данные сохранены.")
    with op.batch_alter_table("operations") as batch:
        batch.alter_column("balance_eod", existing_type=sa.Numeric(16, 2), nullable=False)
    op.drop_table("balance_points")
