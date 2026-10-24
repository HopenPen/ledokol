"""Documents belonging to payment operations.

Revision ID: c93d41ba620f
Revises: b872c30a951e
"""
import sqlalchemy as sa
from alembic import op

from migrations.compat import create_table

revision = 'c93d41ba620f'
down_revision = 'b872c30a951e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table('operation_attachments',
                 sa.Column('id', sa.String(36), primary_key=True),
                 sa.Column('operation_id', sa.String(36), sa.ForeignKey('operations.id', ondelete='CASCADE'), nullable=False),
                 sa.Column('kind', sa.Enum('receipt', 'related', name='attachment_kind', native_enum=False,
                                          create_constraint=True, length=7), nullable=False),
                 sa.Column('filename', sa.String(255), nullable=False),
                 sa.Column('content_type', sa.String(128), nullable=False),
                 sa.Column('size_bytes', sa.Integer(), nullable=False),
                 sa.Column('content', sa.LargeBinary(), nullable=False),
                 sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                 sa.CheckConstraint('size_bytes > 0 AND size_bytes <= 10485760', name='ck_attachment_size'))
    op.create_index('ix_operation_attachments_operation_id', 'operation_attachments', ['operation_id'], if_not_exists=True)
    op.create_index('uq_operation_receipt', 'operation_attachments', ['operation_id'], unique=True,
                    sqlite_where=sa.text("kind = 'receipt'"), postgresql_where=sa.text("kind = 'receipt'"), if_not_exists=True)


def downgrade() -> None:
    op.drop_table('operation_attachments')
