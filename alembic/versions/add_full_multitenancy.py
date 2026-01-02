"""Add full multi-tenancy support and template system

Revision ID: add_full_multitenancy
Revises: add_auth_tables
Create Date: 2025-01-02 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_full_multitenancy"
down_revision: str | None = "add_auth_tables"
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
    op.add_column(
        "users", sa.Column("can_update_uploaded_videos", sa.Boolean(), nullable=False, server_default="true")
    )
    op.add_column("users", sa.Column("can_manage_credentials", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("can_export_data", sa.Boolean(), nullable=False, server_default="true"))

    # ===== 2. Добавление user_id в связанные таблицы =====
    # source_metadata
    op.add_column("source_metadata", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_source_metadata_user_id", "source_metadata", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_source_metadata_user_id", "source_metadata", ["user_id"])

    # output_targets
    op.add_column("output_targets", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_output_targets_user_id", "output_targets", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_output_targets_user_id", "output_targets", ["user_id"])

    # processing_stages
    op.add_column("processing_stages", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_processing_stages_user_id", "processing_stages", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_processing_stages_user_id", "processing_stages", ["user_id"])

    # ===== 3. Создание таблицы base_configs =====
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

    # ===== 4. Создание таблицы input_sources =====
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

    # ===== 5. Создание таблицы output_presets =====
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

    # ===== 6. Создание таблицы recording_templates =====
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

    # Удаление user_id из связанных таблиц
    op.drop_index("ix_processing_stages_user_id", table_name="processing_stages")
    op.drop_constraint("fk_processing_stages_user_id", "processing_stages", type_="foreignkey")
    op.drop_column("processing_stages", "user_id")

    op.drop_index("ix_output_targets_user_id", table_name="output_targets")
    op.drop_constraint("fk_output_targets_user_id", "output_targets", type_="foreignkey")
    op.drop_column("output_targets", "user_id")

    op.drop_index("ix_source_metadata_user_id", table_name="source_metadata")
    op.drop_constraint("fk_source_metadata_user_id", "source_metadata", type_="foreignkey")
    op.drop_column("source_metadata", "user_id")

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

