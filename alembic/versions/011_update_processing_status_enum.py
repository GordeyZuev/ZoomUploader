"""update_processing_status_enum_remove_failed_add_ready_preparing

Revision ID: 011
Revises: 010
Create Date: 2026-01-05 18:29:54.561931

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Обновление enum processingstatus: удаление FAILED, добавление READY и PREPARING."""

    # Шаг 1: Мигрировать записи со статусом FAILED
    # Устанавливаем failed=True и меняем статус на PROCESSED
    op.execute("""
        UPDATE recordings
        SET failed = TRUE,
            status = 'PROCESSED',
            failed_reason = COALESCE(failed_reason, 'Migration from FAILED status')
        WHERE status = 'FAILED'
    """)

    # Шаг 2: Создать временный enum с новыми значениями
    op.execute("""
        CREATE TYPE processingstatus_new AS ENUM (
            'INITIALIZED', 'DOWNLOADING', 'DOWNLOADED', 'PROCESSING', 'PROCESSED',
            'PREPARING', 'TRANSCRIBING', 'TRANSCRIBED', 'UPLOADING', 'UPLOADED',
            'READY', 'SKIPPED', 'EXPIRED'
        )
    """)

    # Шаг 3: Изменить тип колонки с конвертацией (FAILED → PROCESSED уже мигрировано)
    op.execute("""
        ALTER TABLE recordings
        ALTER COLUMN status TYPE processingstatus_new
        USING status::text::processingstatus_new
    """)

    # Шаг 4: Удалить старый enum и переименовать новый
    op.execute("DROP TYPE processingstatus")
    op.execute("ALTER TYPE processingstatus_new RENAME TO processingstatus")


def downgrade() -> None:
    """Откат: вернуть старый enum с FAILED (без PREPARING и READY)."""

    # Создать старый enum
    op.execute("""
        CREATE TYPE processingstatus_old AS ENUM (
            'INITIALIZED', 'DOWNLOADING', 'DOWNLOADED', 'PROCESSING', 'PROCESSED',
            'TRANSCRIBING', 'TRANSCRIBED', 'UPLOADING', 'UPLOADED',
            'SKIPPED', 'EXPIRED', 'FAILED'
        )
    """)

    # Мигрировать новые статусы обратно
    op.execute("""
        UPDATE recordings
        SET status = 'PROCESSED'
        WHERE status IN ('PREPARING', 'READY')
    """)

    # Изменить тип колонки обратно
    op.execute("""
        ALTER TABLE recordings
        ALTER COLUMN status TYPE processingstatus_old
        USING status::text::processingstatus_old
    """)

    # Удалить новый enum и переименовать старый
    op.execute("DROP TYPE processingstatus")
    op.execute("ALTER TYPE processingstatus_old RENAME TO processingstatus")
