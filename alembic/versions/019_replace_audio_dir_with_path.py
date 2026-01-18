"""replace_audio_dir_with_path

Revision ID: 019
Revises: 018
Create Date: 2026-01-12 03:20:00.000000

Заменяем processed_audio_dir на processed_audio_path для хранения
конкретного пути к аудиофайлу вместо директории.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Заменяем processed_audio_dir на processed_audio_path."""
    # 1. Добавляем новое поле
    op.add_column("recordings", sa.Column("processed_audio_path", sa.String(length=1000), nullable=True))

    # 2. Удаляем старое поле (данные будут мигрированы скриптом migrate_audio_paths.py)
    op.drop_column("recordings", "processed_audio_dir")


def downgrade() -> None:
    """Откатываем изменения."""
    # Добавляем обратно старое поле
    op.add_column("recordings", sa.Column("processed_audio_dir", sa.String(length=1000), nullable=True))

    # Удаляем новое поле
    op.drop_column("recordings", "processed_audio_path")
