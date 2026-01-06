"""create_automation_jobs_table

Revision ID: 013
Revises: 012
Create Date: 2026-01-06 15:05:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from alembic import op

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create automation_jobs table for scheduled recording processing."""
    op.create_table(
        'automation_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('template_ids', ARRAY(sa.Integer()), nullable=False, server_default='{}'),
        sa.Column('schedule', JSONB, nullable=False),
        sa.Column(
            'sync_config',
            JSONB,
            nullable=False,
            server_default='{"sync_days": 2, "allow_skipped": false}'
        ),
        sa.Column(
            'processing_config',
            JSONB,
            nullable=False,
            server_default='{"auto_process": true, "auto_upload": true, "max_parallel": 3}'
        ),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('run_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.ForeignKeyConstraint(['source_id'], ['input_sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('idx_automation_jobs_user', 'automation_jobs', ['user_id'])
    op.create_index('idx_automation_jobs_source', 'automation_jobs', ['source_id'])
    op.create_index('idx_automation_jobs_active', 'automation_jobs', ['is_active', 'next_run_at'])
    op.create_index('idx_automation_jobs_schedule', 'automation_jobs', ['schedule'], postgresql_using='gin')


def downgrade() -> None:
    """Drop automation_jobs table."""
    op.drop_index('idx_automation_jobs_schedule', 'automation_jobs')
    op.drop_index('idx_automation_jobs_active', 'automation_jobs')
    op.drop_index('idx_automation_jobs_source', 'automation_jobs')
    op.drop_index('idx_automation_jobs_user', 'automation_jobs')
    op.drop_table('automation_jobs')

