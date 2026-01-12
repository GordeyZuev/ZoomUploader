"""Add blank_record flag to recordings table

Revision ID: 018
Revises: 017
Create Date: 2026-01-11 14:00:00.000000

This migration adds blank_record field to recordings table to support:
- Filtering out short/small recordings (duration < 20 min OR size < 25 MB)
- Hiding blank records from default API listings
- Skipping blank records in processing pipeline
- Includes backfill of existing records
"""
import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

# revision identifiers, used by Alembic.
revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade():
    """Add blank_record field to recordings table."""

    # Add blank_record column
    op.add_column(
        'recordings',
        sa.Column('blank_record', sa.Boolean(), nullable=False, server_default='false')
    )

    # Create index for better query performance
    op.create_index(
        'ix_recordings_blank_record',
        'recordings',
        ['blank_record']
    )

    # Backfill existing records
    MIN_DURATION = 20  # minutes
    MIN_SIZE = 25 * 1024 * 1024  # 25 MB in bytes

    connection = op.get_bind()

    # Update blank records (duration < 20 OR size < 25MB OR size is NULL and duration < 20)
    connection.execute(
        text("""
            UPDATE recordings
            SET blank_record = true
            WHERE duration < :min_duration
               OR video_file_size < :min_size
               OR (video_file_size IS NULL AND duration < :min_duration)
        """),
        {"min_duration": MIN_DURATION, "min_size": MIN_SIZE}
    )

    # Log results
    result = connection.execute(text("SELECT COUNT(*) FROM recordings WHERE blank_record = true"))
    count = result.scalar()
    print(f"✅ Marked {count} existing recordings as blank_record=true")


def downgrade():
    """Remove blank_record field from recordings table."""

    # Drop index
    op.drop_index('ix_recordings_blank_record', table_name='recordings')

    # Drop column
    op.drop_column('recordings', 'blank_record')

