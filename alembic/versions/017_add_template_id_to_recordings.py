"""Add template_id to recordings table

Revision ID: 017
Revises: 016
Create Date: 2026-01-11 12:00:00.000000

This migration adds template_id to recordings table to support:
- Template-driven recording processing
- Linking recordings to their matched template
- Config hierarchy resolution (user_config < template < manual override)
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    """Add template_id field to recordings table."""

    # Add template_id column to recordings
    op.add_column("recordings", sa.Column("template_id", sa.Integer(), nullable=True))

    # Create foreign key constraint
    op.create_foreign_key(
        "fk_recordings_template_id", "recordings", "recording_templates", ["template_id"], ["id"], ondelete="SET NULL"
    )

    # Create index for better query performance
    op.create_index("ix_recordings_template_id", "recordings", ["template_id"])


def downgrade():
    """Remove template_id field from recordings table."""

    # Drop index
    op.drop_index("ix_recordings_template_id", table_name="recordings")

    # Drop foreign key
    op.drop_constraint("fk_recordings_template_id", "recordings", type_="foreignkey")

    # Drop column
    op.drop_column("recordings", "template_id")
