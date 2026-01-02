"""Add authentication and multi-tenancy tables

Revision ID: add_auth_tables
Revises: 59461e085eec
Create Date: 2025-01-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_auth_tables"
down_revision: str | None = "59461e085eec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Создание таблицы users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"])

    # Создание таблицы user_credentials
    op.create_table(
        "user_credentials",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("encrypted_data", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_credentials_user_id", "user_credentials", ["user_id"])

    # Создание таблицы user_quotas
    op.create_table(
        "user_quotas",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("max_recordings_per_month", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("max_storage_gb", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("max_concurrent_tasks", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("current_recordings_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_storage_gb", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_tasks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quota_reset_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_user_quotas_user_id", "user_quotas", ["user_id"])

    # Создание таблицы refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=500), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_refresh_tokens_token", "refresh_tokens", ["token"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    # Добавление user_id в таблицу recordings (nullable для обратной совместимости)
    op.add_column("recordings", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_recordings_user_id", "recordings", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_recordings_user_id", "recordings", ["user_id"])


def downgrade() -> None:
    # Удаление user_id из recordings
    op.drop_index("ix_recordings_user_id", table_name="recordings")
    op.drop_constraint("fk_recordings_user_id", "recordings", type_="foreignkey")
    op.drop_column("recordings", "user_id")

    # Удаление таблиц
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_token", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_user_quotas_user_id", table_name="user_quotas")
    op.drop_table("user_quotas")

    op.drop_index("ix_user_credentials_user_id", table_name="user_credentials")
    op.drop_table("user_credentials")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
