"""add_automation_quotas_to_user_quotas

Revision ID: 012
Revises: 011
Create Date: 2026-01-06 15:00:00.000000

"""
import sqlalchemy as sa

from alembic import op

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add automation quota fields to user_quotas table."""
    op.add_column(
        'user_quotas',
        sa.Column('max_automation_jobs', sa.Integer(), nullable=False, server_default='5')
    )
    op.add_column(
        'user_quotas',
        sa.Column('min_automation_interval_hours', sa.Integer(), nullable=False, server_default='1')
    )


def downgrade() -> None:
    """Remove automation quota fields from user_quotas table."""
    op.drop_column('user_quotas', 'min_automation_interval_hours')
    op.drop_column('user_quotas', 'max_automation_jobs')

