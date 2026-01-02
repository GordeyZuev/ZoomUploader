"""add_transcription_fields

Revision ID: 59461e085eec
Revises:
Create Date: 2025-11-09 17:39:24.303068

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "59461e085eec"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем поля для транскрипции и тем
    op.add_column("recordings", sa.Column("transcription_file_path", sa.String(length=1000), nullable=True))
    op.add_column("recordings", sa.Column("topic_timestamps", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("recordings", sa.Column("main_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    # Удаляем поля транскрипции
    op.drop_column("recordings", "main_topics")
    op.drop_column("recordings", "topic_timestamps")
    op.drop_column("recordings", "transcription_file_path")
