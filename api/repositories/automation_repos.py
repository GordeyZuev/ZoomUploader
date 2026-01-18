"""Automation job repository"""

from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.automation_models import AutomationJobModel


class AutomationJobRepository:
    """Repository for managing automation jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, job_data: dict, user_id: int) -> AutomationJobModel:
        """Create new automation job."""
        now = datetime.utcnow()
        job = AutomationJobModel(**job_data, user_id=user_id, created_at=now, updated_at=now)
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get_by_id(self, job_id: int, user_id: int) -> AutomationJobModel | None:
        """Get automation job by ID (with user ownership check)."""
        stmt = select(AutomationJobModel).where(
            and_(AutomationJobModel.id == job_id, AutomationJobModel.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_jobs(self, user_id: int, active_only: bool = False) -> list[AutomationJobModel]:
        """Get all jobs for user."""
        stmt = select(AutomationJobModel).where(AutomationJobModel.user_id == user_id)
        if active_only:
            stmt = stmt.where(AutomationJobModel.is_active == True)  # noqa: E712
        stmt = stmt.order_by(AutomationJobModel.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_user_jobs(self, user_id: int) -> int:
        """Count total jobs for user."""
        stmt = select(AutomationJobModel).where(AutomationJobModel.user_id == user_id)
        result = await self.session.execute(stmt)
        return len(list(result.scalars().all()))

    async def get_all_active_jobs(self) -> list[AutomationJobModel]:
        """Get all active jobs across all users (for Celery Beat sync)."""
        stmt = select(AutomationJobModel).where(AutomationJobModel.is_active == True)  # noqa: E712
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, job: AutomationJobModel, updates: dict) -> AutomationJobModel:
        """Update automation job."""
        for key, value in updates.items():
            if value is not None and hasattr(job, key):
                setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def delete(self, job: AutomationJobModel) -> None:
        """Delete automation job."""
        await self.session.delete(job)
        await self.session.commit()

    async def mark_run(self, job: AutomationJobModel, next_run_at: datetime) -> None:
        """Mark job as run and update stats."""
        job.last_run_at = datetime.utcnow()
        job.next_run_at = next_run_at
        job.run_count += 1
        await self.session.commit()
