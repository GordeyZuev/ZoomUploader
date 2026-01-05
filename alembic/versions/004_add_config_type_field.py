"""Add config_type field to base_configs table

Revision ID: 004
Revises: 003
Create Date: 2026-01-04 23:03:00.000000

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add config_type field to base_configs table."""
    # Add config_type column
    op.add_column(
        "base_configs",
        sa.Column("config_type", sa.String(length=50), nullable=True),
    )

    # Add index on config_type for faster lookups
    op.create_index(
        op.f("ix_base_configs_config_type"),
        "base_configs",
        ["config_type"],
        unique=False,
    )


def downgrade() -> None:
    """Remove config_type field from base_configs table."""
    # Drop index
    op.drop_index(op.f("ix_base_configs_config_type"), table_name="base_configs")

    # Drop column
    op.drop_column("base_configs", "config_type")

