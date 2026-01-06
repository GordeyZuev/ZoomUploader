"""Business logic service for automation jobs."""

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.helpers.schedule_converter import get_next_run_time, schedule_to_cron, validate_min_interval
from api.repositories.auth_repos import UserQuotaRepository
from api.repositories.automation_repos import AutomationJobRepository
from database.auth_models import UserQuotaModel


class AutomationService:
    """Service for managing automation jobs with business logic."""

    def __init__(self, session: AsyncSession, user_id: int):
        self.session = session
        self.user_id = user_id
        self.job_repo = AutomationJobRepository(session)
        self.quota_repo = UserQuotaRepository(session)

    async def get_user_quota(self) -> UserQuotaModel:
        """Get user quota or raise error."""
        quota = await self.quota_repo.get(self.user_id)
        if not quota:
            raise HTTPException(status_code=404, detail="User quota not found")
        return quota

    async def validate_quota(self) -> UserQuotaModel:
        """Validate that user hasn't exceeded automation job limit."""
        quota = await self.get_user_quota()
        current_count = await self.job_repo.count_user_jobs(self.user_id)

        if current_count >= quota.max_automation_jobs:
            raise HTTPException(
                status_code=400,
                detail=f"Automation job limit reached ({quota.max_automation_jobs} jobs maximum)"
            )

        return quota

    async def validate_schedule(self, schedule: dict, quota: UserQuotaModel) -> None:
        """Validate that schedule meets minimum interval requirement."""
        cron_expr, _ = schedule_to_cron(schedule)

        if not validate_min_interval(cron_expr, quota.min_automation_interval_hours):
            raise HTTPException(
                status_code=400,
                detail=f"Schedule interval must be at least {quota.min_automation_interval_hours} hour(s)"
            )

    async def prepare_job_data(self, job_data: dict) -> dict:
        """Prepare job data with calculated next_run_at."""
        cron_expr, human = schedule_to_cron(job_data["schedule"])
        timezone = job_data["schedule"].get("timezone", "Europe/Moscow")
        next_run = get_next_run_time(cron_expr, timezone)

        job_data["next_run_at"] = next_run

        return job_data

    async def create_job(self, job_data: dict):
        """Create new automation job with validation."""
        quota = await self.validate_quota()
        await self.validate_schedule(job_data["schedule"], quota)

        job_data = await self.prepare_job_data(job_data)

        return await self.job_repo.create(job_data, self.user_id)

    async def update_job(self, job_id: int, updates: dict):
        """Update automation job with validation."""
        job = await self.job_repo.get_by_id(job_id, self.user_id)
        if not job:
            raise HTTPException(status_code=404, detail="Automation job not found")

        if "schedule" in updates:
            quota = await self.get_user_quota()
            await self.validate_schedule(updates["schedule"], quota)

            cron_expr, _ = schedule_to_cron(updates["schedule"])
            timezone = updates["schedule"].get("timezone", "Europe/Moscow")
            updates["next_run_at"] = get_next_run_time(cron_expr, timezone)

        return await self.job_repo.update(job, updates)

