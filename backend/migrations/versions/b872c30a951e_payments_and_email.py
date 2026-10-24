"""Bank account binding, manual payment idempotency and email verification.

Revision ID: b872c30a951e
Revises: a51c3667275f
"""
import sqlalchemy as sa
from alembic import op

from migrations.compat import create_table

revision = "b872c30a951e"
down_revision = "a51c3667275f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table("bank_accounts",
                    sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
                    sa.Column("number", sa.String(20), nullable=False),
                    sa.UniqueConstraint("owner_id", "number", name="uq_owner_bank_account"))
    create_table("manual_payment_requests",
                    sa.Column("company_id", sa.String(36), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("key", sa.String(64), primary_key=True),
                    sa.Column("request_hash", sa.String(64), nullable=False),
                    sa.Column("operation_id", sa.String(36), sa.ForeignKey("operations.id", ondelete="CASCADE"), nullable=False),
                    sa.UniqueConstraint("operation_id"), column_renames={"idempotency_key": "key"})
    create_table("user_emails",
                    sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("email", sa.String(254), nullable=False),
                    sa.Column("email_key", sa.String(254), nullable=False),
                    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("token_hash", sa.String(64), nullable=True),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=False),
                    sa.UniqueConstraint("email_key"), sa.UniqueConstraint("token_hash"))


def downgrade() -> None:
    op.drop_table("user_emails")
    op.drop_table("manual_payment_requests")
    op.drop_table("bank_accounts")
