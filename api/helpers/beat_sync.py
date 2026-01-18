"""Automation jobs and Celery Beat synchronization"""

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.helpers.schedule_converter import schedule_to_cron
from database.automation_models import AutomationJobModel

logger = logging.getLogger(__name__)


async def sync_job_to_beat(session: AsyncSession, job: AutomationJobModel) -> None:
    """
    Sync automation job to Celery Beat periodic task.
    Creates or updates crontab schedule and periodic task.
    """
    try:
        cron_expr, _ = schedule_to_cron(job.schedule)
        minute, hour, day, month, day_of_week = cron_expr.split()
        timezone = job.schedule.get("timezone", "UTC")

        # Step 1: Create or get crontab schedule
        crontab_query = text("""
            INSERT INTO celery_crontab_schedule (minute, hour, day_of_month, month_of_year, day_of_week, timezone)
            VALUES (:minute, :hour, :day, :month, :dow, :tz)
            ON CONFLICT DO NOTHING
            RETURNING id
        """)

        result = await session.execute(
            crontab_query,
            {"minute": minute, "hour": hour, "day": day, "month": month, "dow": day_of_week, "tz": timezone},
        )
        crontab_id = result.scalar_one_or_none()

        if not crontab_id:
            select_crontab = text("""
                SELECT id FROM celery_crontab_schedule
                WHERE minute = :minute AND hour = :hour AND day_of_month = :day
                  AND month_of_year = :month AND day_of_week = :dow AND timezone = :tz
            """)
            result = await session.execute(
                select_crontab,
                {"minute": minute, "hour": hour, "day": day, "month": month, "dow": day_of_week, "tz": timezone},
            )
            crontab_id = result.scalar_one()

        # Step 2: Create or update periodic task
        task_name = f"automation_job_{job.id}"
        args_json = json.dumps([job.id, job.user_id])

        upsert_task = text("""
            INSERT INTO celery_periodic_task (name, task, crontab_id, args, enabled)
            VALUES (:name, :task, :crontab_id, :args, :enabled)
            ON CONFLICT (name) DO UPDATE
            SET crontab_id = EXCLUDED.crontab_id,
                enabled = EXCLUDED.enabled,
                date_changed = NOW()
        """)

        await session.execute(
            upsert_task,
            {
                "name": task_name,
                "task": "automation.run_job",
                "crontab_id": crontab_id,
                "args": args_json,
                "enabled": job.is_active,
            },
        )

        await session.commit()
        logger.info(f"Synced automation job {job.id} to Celery Beat")

    except Exception as e:
        logger.error(f"Failed to sync job {job.id} to Beat: {e}")
        await session.rollback()
        raise


async def remove_job_from_beat(session: AsyncSession, job_id: int) -> None:
    """Remove automation job from Celery Beat."""
    try:
        task_name = f"automation_job_{job_id}"

        delete_task = text("""
            DELETE FROM celery_periodic_task
            WHERE name = :name
        """)

        await session.execute(delete_task, {"name": task_name})
        await session.commit()

        logger.info(f"Removed automation job {job_id} from Celery Beat")

    except Exception as e:
        logger.error(f"Failed to remove job {job_id} from Beat: {e}")
        await session.rollback()
        raise


async def sync_all_jobs_to_beat(session: AsyncSession) -> None:
    """Sync all active automation jobs to Celery Beat (on startup)."""
    from api.repositories.automation_repos import AutomationJobRepository

    try:
        job_repo = AutomationJobRepository(session)
        jobs = await job_repo.get_all_active_jobs()

        logger.info(f"Syncing {len(jobs)} active automation jobs to Celery Beat")

        for job in jobs:
            await sync_job_to_beat(session, job)

        logger.info("All automation jobs synced to Celery Beat")

    except Exception as e:
        logger.error(f"Failed to sync jobs to Beat: {e}")
        raise
