"""Add foreign keys to input sources and output presets

Revision ID: 006
Revises: 005
Create Date: 2026-01-04 23:05:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем foreign key для input_source_id в recordings
    # (столбец уже создан в миграции 001, но FK можно добавить только после создания input_sources в миграции 003)
    op.create_foreign_key(
        "fk_recordings_input_source_id", "recordings", "input_sources", ["input_source_id"], ["id"], ondelete="SET NULL"
    )

    # Добавляем foreign key для input_source_id в source_metadata
    # (столбец уже создан в миграции 001, но FK можно добавить только после создания input_sources в миграции 003)
    op.create_foreign_key(
        "fk_source_metadata_input_source_id",
        "source_metadata",
        "input_sources",
        ["input_source_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Добавляем foreign key для preset_id в output_targets
    # (столбец уже создан в миграции 001, но FK можно добавить только после создания output_presets в миграции 003)
    op.create_foreign_key(
        "fk_output_targets_preset_id", "output_targets", "output_presets", ["preset_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    # Удаляем foreign keys в обратном порядке
    op.drop_constraint("fk_output_targets_preset_id", "output_targets", type_="foreignkey")
    op.drop_constraint("fk_source_metadata_input_source_id", "source_metadata", type_="foreignkey")
    op.drop_constraint("fk_recordings_input_source_id", "recordings", type_="foreignkey")
