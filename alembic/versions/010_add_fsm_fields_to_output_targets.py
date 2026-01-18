"""add_fsm_fields_to_output_targets

Revision ID: 010
Revises: 009
Create Date: 2026-01-05 18:28:46.313586

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавление FSM полей в output_targets для отслеживания ошибок."""
    # Добавляем FSM поля
    op.add_column("output_targets", sa.Column("failed", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("output_targets", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("output_targets", sa.Column("failed_reason", sa.String(length=1000), nullable=True))
    op.add_column("output_targets", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Откат: удаление FSM полей из output_targets."""
    op.drop_column("output_targets", "retry_count")
    op.drop_column("output_targets", "failed_reason")
    op.drop_column("output_targets", "failed_at")
    op.drop_column("output_targets", "failed")
