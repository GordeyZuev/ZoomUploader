"""create_celery_beat_scheduler_tables

Revision ID: 014
Revises: 013
Create Date: 2026-01-06 15:10:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create tables for celery-sqlalchemy-scheduler."""

    # Interval Schedule Table
    op.create_table(
        "celery_interval_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("every", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Crontab Schedule Table
    op.create_table(
        "celery_crontab_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("minute", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("hour", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("day_of_week", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("day_of_month", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("month_of_year", sa.String(length=64), nullable=False, server_default="*"),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Solar Schedule Table (for solar events, optional but included for completeness)
    op.create_table(
        "celery_solar_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=24), nullable=False),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Periodic Task Table
    op.create_table(
        "celery_periodic_task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, unique=True),
        sa.Column("task", sa.String(length=200), nullable=False),
        sa.Column("interval_id", sa.Integer(), nullable=True),
        sa.Column("crontab_id", sa.Integer(), nullable=True),
        sa.Column("solar_id", sa.Integer(), nullable=True),
        sa.Column("args", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("kwargs", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("queue", sa.String(length=200), nullable=True),
        sa.Column("exchange", sa.String(length=200), nullable=True),
        sa.Column("routing_key", sa.String(length=200), nullable=True),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("date_changed", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["crontab_id"], ["celery_crontab_schedule.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["interval_id"], ["celery_interval_schedule.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["solar_id"], ["celery_solar_schedule.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("idx_celery_periodic_task_name", "celery_periodic_task", ["name"], unique=True)
    op.create_index("idx_celery_periodic_task_enabled", "celery_periodic_task", ["enabled"])


def downgrade() -> None:
    """Drop celery-sqlalchemy-scheduler tables."""
    op.drop_index("idx_celery_periodic_task_enabled", "celery_periodic_task")
    op.drop_index("idx_celery_periodic_task_name", "celery_periodic_task")
    op.drop_table("celery_periodic_task")
    op.drop_table("celery_solar_schedule")
    op.drop_table("celery_crontab_schedule")
    op.drop_table("celery_interval_schedule")
