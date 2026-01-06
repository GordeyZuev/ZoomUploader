"""Add unique constraint to input sources

Revision ID: 009
Revises: 008
Create Date: 2026-01-05 17:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Добавляем уникальное ограничение для предотвращения дубликатов источников.

    Источник считается уникальным по комбинации:
    - user_id: пользователь
    - name: название источника
    - source_type: тип источника (ZOOM, LOCAL, YANDEX_DISK, etc)
    - credential_id: используемые credentials
    """
    # Сначала удаляем существующие дубликаты (если они есть)
    # Оставляем только запись с наименьшим ID для каждой группы дубликатов
    op.execute("""
        DELETE FROM input_sources
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM input_sources
            GROUP BY user_id, name, source_type, COALESCE(credential_id, -1)
        )
    """)

    # Добавляем уникальное ограничение
    op.create_unique_constraint(
        'uq_input_sources_user_name_type_credential',
        'input_sources',
        ['user_id', 'name', 'source_type', 'credential_id']
    )


def downgrade() -> None:
    """Удаляем уникальное ограничение."""
    op.drop_constraint(
        'uq_input_sources_user_name_type_credential',
        'input_sources',
        type_='unique'
    )

