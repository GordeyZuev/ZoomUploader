"""Add config_type field to base_configs table

Revision ID: add_config_type_field
Revises: add_full_multitenancy
Create Date: 2025-01-02 12:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_config_type_field"
down_revision = "add_full_multitenancy"
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

