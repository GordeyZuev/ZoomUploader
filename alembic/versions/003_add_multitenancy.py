"""Add full multi-tenancy support and template system

Revision ID: 003
Revises: 002
Create Date: 2026-01-04 23:02:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ===== 1. Добавление ролей и прав в users =====
    op.add_column("users", sa.Column("role", sa.String(length=50), nullable=False, server_default="user"))
    op.add_column("users", sa.Column("can_transcribe", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_process_video", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_upload", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_create_templates", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_delete_recordings", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_update_uploaded_videos", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_manage_credentials", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_export_data", sa.Boolean(), nullable=False, server_default="true"))

    # ===== 2. Создание таблицы base_configs =====
    op.create_table(
        "base_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_base_configs_user_id", "base_configs", ["user_id"])

    # ===== 3. Создание таблицы input_sources =====
    op.create_table(
        "input_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["credential_id"], ["user_credentials.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_sources_user_id", "input_sources", ["user_id"])

    # ===== 4. Создание таблицы output_presets =====
    op.create_table(
        "output_presets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("credential_id", sa.Integer(), nullable=False),
        sa.Column("preset_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["credential_id"], ["user_credentials.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_output_presets_user_id", "output_presets", ["user_id"])

    # ===== 5. Создание таблицы recording_templates =====
    op.create_table(
        "recording_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("matching_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processing_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_draft", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recording_templates_user_id", "recording_templates", ["user_id"])
    op.create_index("ix_recording_templates_priority", "recording_templates", ["priority"])


def downgrade() -> None:
    # Удаление таблиц (в обратном порядке)
    op.drop_index("ix_recording_templates_priority", table_name="recording_templates")
    op.drop_index("ix_recording_templates_user_id", table_name="recording_templates")
    op.drop_table("recording_templates")

    op.drop_index("ix_output_presets_user_id", table_name="output_presets")
    op.drop_table("output_presets")

    op.drop_index("ix_input_sources_user_id", table_name="input_sources")
    op.drop_table("input_sources")

    op.drop_index("ix_base_configs_user_id", table_name="base_configs")
    op.drop_table("base_configs")

    # Удаление ролей и прав из users
    op.drop_column("users", "can_export_data")
    op.drop_column("users", "can_manage_credentials")
    op.drop_column("users", "can_update_uploaded_videos")
    op.drop_column("users", "can_delete_recordings")
    op.drop_column("users", "can_create_templates")
    op.drop_column("users", "can_upload")
    op.drop_column("users", "can_process_video")
    op.drop_column("users", "can_transcribe")
    op.drop_column("users", "role")
