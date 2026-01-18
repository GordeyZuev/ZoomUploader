"""Add timezone to users

Revision ID: 015_add_timezone
Revises: 014_create_celery_beat_tables
Create Date: 2026-01-07 03:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    """Add timezone column to users table."""
    op.add_column("users", sa.Column("timezone", sa.String(length=50), server_default="UTC", nullable=False))


def downgrade():
    """Remove timezone column from users table."""
    op.drop_column("users", "timezone")
