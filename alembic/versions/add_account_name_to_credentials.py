"""Add account_name to user_credentials for multiple accounts per platform

Revision ID: add_account_name_to_credentials
Revises: add_config_type_field
Create Date: 2025-01-02 14:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_account_name_to_credentials"
down_revision = "add_config_type_field"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add account_name field to user_credentials table."""
    # Add account_name column (nullable for backward compatibility)
    op.add_column(
        "user_credentials",
        sa.Column("account_name", sa.String(length=255), nullable=True),
    )

    # Drop old unique constraint on (user_id, platform) if exists
    # Note: constraint name might vary, adjust if needed
    try:
        op.drop_constraint("uq_user_credentials_user_platform", "user_credentials", type_="unique")
    except Exception:
        pass  # Constraint might not exist

    # Create new unique constraint on (user_id, platform, account_name)
    # This allows multiple accounts per platform
    op.create_index(
        "ix_user_credentials_user_platform_account",
        "user_credentials",
        ["user_id", "platform", "account_name"],
        unique=True,
    )


def downgrade() -> None:
    """Remove account_name field from user_credentials table."""
    # Drop new unique constraint
    op.drop_index("ix_user_credentials_user_platform_account", table_name="user_credentials")

    # Restore old constraint (if needed)
    # op.create_unique_constraint("uq_user_credentials_user_platform", "user_credentials", ["user_id", "platform"])

    # Drop column
    op.drop_column("user_credentials", "account_name")

