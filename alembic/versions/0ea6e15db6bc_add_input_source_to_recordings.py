"""add_input_source_to_recordings

Revision ID: 0ea6e15db6bc
Revises: add_account_name_to_credentials
Create Date: 2026-01-02 20:40:37.691305

"""
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = '0ea6e15db6bc'
down_revision = 'add_account_name_to_credentials'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Добавляем input_source_id в recordings
    op.add_column('recordings', sa.Column('input_source_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_recordings_input_source_id',
        'recordings',
        'input_sources',
        ['input_source_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_recordings_input_source_id', 'recordings', ['input_source_id'])

    # Добавляем input_source_id в source_metadata для связности
    op.add_column('source_metadata', sa.Column('input_source_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_source_metadata_input_source_id',
        'source_metadata',
        'input_sources',
        ['input_source_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_source_metadata_input_source_id', 'source_metadata', ['input_source_id'])

    # Добавляем preset_id в output_targets для связи с output presets
    op.add_column('output_targets', sa.Column('preset_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_output_targets_preset_id',
        'output_targets',
        'output_presets',
        ['preset_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_output_targets_preset_id', 'output_targets', ['preset_id'])


def downgrade() -> None:
    # Удаляем в обратном порядке
    op.drop_index('ix_output_targets_preset_id', table_name='output_targets')
    op.drop_constraint('fk_output_targets_preset_id', 'output_targets', type_='foreignkey')
    op.drop_column('output_targets', 'preset_id')

    op.drop_index('ix_source_metadata_input_source_id', table_name='source_metadata')
    op.drop_constraint('fk_source_metadata_input_source_id', 'source_metadata', type_='foreignkey')
    op.drop_column('source_metadata', 'input_source_id')

    op.drop_index('ix_recordings_input_source_id', table_name='recordings')
    op.drop_constraint('fk_recordings_input_source_id', 'recordings', type_='foreignkey')
    op.drop_column('recordings', 'input_source_id')
