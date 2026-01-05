"""Create base tables

Revision ID: 001
Revises:
Create Date: 2026-01-04 23:00:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу recordings
    op.create_table(
        "recordings",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("input_source_id", sa.Integer(), nullable=True),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("INITIALIZED", "SKIPPED", "DOWNLOADED", "PROCESSED", "TRANSCRIBED", "UPLOADED", "FAILED", "EXPIRED", name="processingstatus"), nullable=True),
        sa.Column("is_mapped", sa.Boolean(), nullable=True),
        sa.Column("expire_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("local_video_path", sa.String(length=1000), nullable=True),
        sa.Column("processed_video_path", sa.String(length=1000), nullable=True),
        sa.Column("processed_audio_dir", sa.String(length=1000), nullable=True),
        sa.Column("transcription_dir", sa.String(length=1000), nullable=True),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("video_file_size", sa.Integer(), nullable=True),
        sa.Column("transcription_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("topic_timestamps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("main_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processing_preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.String(length=1000), nullable=True),
        sa.Column("failed_at_stage", sa.String(length=50), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recordings_user_id"), "recordings", ["user_id"], unique=False)
    op.create_index(op.f("ix_recordings_input_source_id"), "recordings", ["input_source_id"], unique=False)

    # Создаем таблицу source_metadata
    op.create_table(
        "source_metadata",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("input_source_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.Enum("ZOOM", "LOCAL_FILE", "GOOGLE_DRIVE", "YOUTUBE", "OTHER", name="sourcetype"), nullable=True),
        sa.Column("source_key", sa.String(length=1000), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recording_id"),
        sa.UniqueConstraint("source_type", "source_key", "recording_id", name="unique_source_per_recording"),
    )
    op.create_index(op.f("ix_source_metadata_user_id"), "source_metadata", ["user_id"], unique=False)
    op.create_index(op.f("ix_source_metadata_input_source_id"), "source_metadata", ["input_source_id"], unique=False)

    # Создаем таблицу output_targets
    op.create_table(
        "output_targets",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("preset_id", sa.Integer(), nullable=True),
        sa.Column("target_type", sa.Enum("YOUTUBE", "VK", "LOCAL_STORAGE", "GOOGLE_DRIVE", "OTHER", name="targettype"), nullable=True),
        sa.Column("status", sa.Enum("NOT_UPLOADED", "UPLOADING", "UPLOADED", "FAILED", name="targetstatus"), nullable=True),
        sa.Column("target_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recording_id", "target_type", name="unique_target_per_recording"),
    )
    op.create_index(op.f("ix_output_targets_user_id"), "output_targets", ["user_id"], unique=False)
    op.create_index(op.f("ix_output_targets_preset_id"), "output_targets", ["preset_id"], unique=False)

    # Создаем таблицу processing_stages
    op.create_table(
        "processing_stages",
        sa.Column("id", sa.Integer(), sa.Identity(), nullable=False),
        sa.Column("recording_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("stage_type", sa.Enum("DOWNLOAD", "PROCESS_VIDEO", "TRANSCRIBE", "EXTRACT_TOPICS", "GENERATE_SUBTITLES", "UPLOAD", name="processingstagetype"), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", name="processingstagestatus"), nullable=True),
        sa.Column("failed", sa.Boolean(), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_reason", sa.String(length=1000), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("stage_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recording_id", "stage_type", name="unique_stage_per_recording"),
    )
    op.create_index(op.f("ix_processing_stages_user_id"), "processing_stages", ["user_id"], unique=False)


def downgrade() -> None:
    # Удаляем таблицы в обратном порядке
    op.drop_table("processing_stages")
    op.drop_table("output_targets")
    op.drop_table("source_metadata")
    op.drop_table("recordings")

