# 🤖 Automation Implementation Plan

**Feature:** Automated recording sync and processing with Celery Beat  
**Status:** 🚧 In Progress  
**Version:** v2.7

---

## 🎯 Overview

Автоматизация sync + processing + upload записей по расписанию:
- **Декларативный подход** к расписанию (time_of_day, hours, weekdays, cron)
- **Celery Beat** для distributed scheduling
- **celery-sqlalchemy-scheduler** для хранения в PostgreSQL
- **Dry-run mode** для preview
- **Quota management** (max 5 jobs per user, min 1 hour interval)

---

## 📋 Implementation Checklist

### Phase 1: Database Setup ✅
- [ ] Migration 012: Add automation quotas to `user_quotas`
- [ ] Migration 013: Create `automation_jobs` table
- [ ] Migration 014: Create celery-sqlalchemy-scheduler tables

### Phase 2: Models & Schemas ✅
- [ ] `database/automation_models.py` - SQLAlchemy models
- [ ] `api/schemas/automation/schedule.py` - Декларативные schedule types
- [ ] `api/schemas/automation/job.py` - AutomationJob schemas

### Phase 3: Core Logic ✅
- [ ] `api/helpers/schedule_converter.py` - Schedule to cron conversion
- [ ] `api/repositories/automation_repos.py` - Database operations
- [ ] `api/services/automation_service.py` - Business logic

### Phase 4: Celery Integration ✅
- [ ] `api/tasks/automation.py` - Celery tasks
- [ ] `api/celery_app.py` - Setup celery-sqlalchemy-scheduler
- [ ] Beat schedule sync logic

### Phase 5: API Endpoints ✅
- [ ] `api/routers/automation.py` - REST API
- [ ] Quota validation middleware
- [ ] Dry-run mode

### Phase 6: Testing & Docs ✅
- [ ] Update `requirements.txt`
- [ ] Makefile commands
- [ ] Update `WHAT_WAS_DONE.md`

---

## 🗄️ Database Schema

### Migration 012: Automation Quotas

**File:** `alembic/versions/012_add_automation_quotas.py`

```python
def upgrade():
    op.add_column('user_quotas', sa.Column('max_automation_jobs', sa.Integer(), server_default='5', nullable=False))
    op.add_column('user_quotas', sa.Column('min_automation_interval_hours', sa.Integer(), server_default='1', nullable=False))

def downgrade():
    op.drop_column('user_quotas', 'min_automation_interval_hours')
    op.drop_column('user_quotas', 'max_automation_jobs')
```

---

### Migration 013: Automation Jobs

**File:** `alembic/versions/013_create_automation_jobs.py`

```sql
CREATE TABLE automation_jobs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Basic info
    name VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- Source to sync
    source_id INTEGER NOT NULL REFERENCES input_sources(id) ON DELETE CASCADE,
    
    -- Templates to apply (ARRAY)
    template_ids INTEGER[] DEFAULT '{}',  -- Empty = all active templates
    
    -- Schedule config (JSONB)
    schedule JSONB NOT NULL,
    -- Examples:
    -- {"type": "time_of_day", "time": "06:00", "timezone": "Europe/Moscow"}
    -- {"type": "hours", "hours": 6, "timezone": "Europe/Moscow"}
    -- {"type": "weekdays", "days": [1,2,3,4,5], "time": "09:00", "timezone": "Europe/Moscow"}
    -- {"type": "cron", "expression": "0 6 * * *", "timezone": "Europe/Moscow"}
    
    -- Sync config (JSONB)
    sync_config JSONB NOT NULL DEFAULT '{"sync_days": 2, "allow_skipped": false}',
    
    -- Processing config (JSONB)
    processing_config JSONB NOT NULL DEFAULT '{"auto_process": true, "auto_upload": true, "max_parallel": 3}',
    
    -- State
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    run_count INTEGER NOT NULL DEFAULT 0,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_automation_jobs_user ON automation_jobs(user_id);
CREATE INDEX idx_automation_jobs_source ON automation_jobs(source_id);
CREATE INDEX idx_automation_jobs_active ON automation_jobs(is_active, next_run_at);
CREATE INDEX idx_automation_jobs_schedule ON automation_jobs USING GIN(schedule);
```

---

### Migration 014: Celery Beat Tables

**File:** `alembic/versions/014_create_celery_beat_tables.py`

Использовать схему из `celery-sqlalchemy-scheduler`:
- `celery_periodic_task`
- `celery_interval_schedule`
- `celery_crontab_schedule`
- `celery_solar_schedule`

---

## 🏗️ Models

### File: `database/automation_models.py`

```python
from sqlalchemy import Column, Integer, String, Text, Boolean, ARRAY, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from database.config import Base

class AutomationJobModel(Base):
    __tablename__ = "automation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False)
    template_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list, server_default="{}")
    
    schedule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sync_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{"sync_days": 2, "allow_skipped": false}')
    processing_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default='{"auto_process": true, "auto_upload": true, "max_parallel": 3}')
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    user = relationship("UserModel", back_populates="automation_jobs")
    source = relationship("InputSourceModel")
```

### Update: `database/auth_models.py`

```python
class UserQuotasModel(Base):
    # ... existing fields ...
    
    max_automation_jobs: Mapped[int] = mapped_column(Integer, default=5, server_default="5", nullable=False)
    min_automation_interval_hours: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
```

### Update: `database/auth_models.py` - UserModel

```python
class UserModel(Base):
    # ... existing relationships ...
    automation_jobs = relationship("AutomationJobModel", back_populates="user", cascade="all, delete-orphan")
```

---

## 📝 Schemas

### File: `api/schemas/automation/schedule.py`

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Annotated
from enum import Enum

class ScheduleType(str, Enum):
    TIME_OF_DAY = "time_of_day"
    HOURS = "hours"
    WEEKDAYS = "weekdays"
    CRON = "cron"

class TimeOfDaySchedule(BaseModel):
    type: Literal["time_of_day"]
    time: str = Field(pattern=r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = "Europe/Moscow"
    
    def to_cron(self) -> str:
        hour, minute = self.time.split(":")
        return f"{minute} {hour} * * *"
    
    def human_readable(self) -> str:
        return f"Daily at {self.time}"

class HoursSchedule(BaseModel):
    type: Literal["hours"]
    hours: int = Field(ge=1, le=24)
    timezone: str = "Europe/Moscow"
    
    def to_cron(self) -> str:
        return f"0 */{self.hours} * * *"
    
    def human_readable(self) -> str:
        return f"Every {self.hours} hour(s)"

class WeekdaysSchedule(BaseModel):
    type: Literal["weekdays"]
    days: list[int] = Field(min_length=1, max_length=7)
    time: str = Field(pattern=r"^([0-1][0-9]|2[0-3]):[0-5][0-9]$")
    timezone: str = "Europe/Moscow"
    
    @field_validator("days")
    @classmethod
    def validate_days(cls, v):
        if not all(0 <= day <= 6 for day in v):
            raise ValueError("Days must be 0-6 (0=Monday)")
        return sorted(set(v))
    
    def to_cron(self) -> str:
        hour, minute = self.time.split(":")
        days_cron = ",".join(str((d + 1) % 7) for d in self.days)
        return f"{minute} {hour} * * {days_cron}"
    
    def human_readable(self) -> str:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days_str = ", ".join(day_names[d] for d in self.days)
        return f"Weekly on {days_str} at {self.time}"

class CronSchedule(BaseModel):
    type: Literal["cron"]
    expression: str
    timezone: str = "Europe/Moscow"
    
    def to_cron(self) -> str:
        return self.expression
    
    def human_readable(self) -> str:
        return f"Custom: {self.expression}"

Schedule = Annotated[
    TimeOfDaySchedule | HoursSchedule | WeekdaysSchedule | CronSchedule,
    Field(discriminator="type")
]
```

---

### File: `api/schemas/automation/job.py`

```python
from pydantic import BaseModel, Field
from datetime import datetime
from .schedule import Schedule

class SyncConfig(BaseModel):
    sync_days: int = Field(default=2, ge=1, le=30)
    allow_skipped: bool = False

class ProcessingConfig(BaseModel):
    auto_process: bool = True
    auto_upload: bool = True
    max_parallel: int = Field(default=3, ge=1, le=10)

class AutomationJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    source_id: int
    template_ids: list[int] = Field(default_factory=list)
    schedule: Schedule
    sync_config: SyncConfig = Field(default_factory=SyncConfig)
    processing_config: ProcessingConfig = Field(default_factory=ProcessingConfig)

class AutomationJobUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    template_ids: list[int] | None = None
    schedule: Schedule | None = None
    sync_config: SyncConfig | None = None
    processing_config: ProcessingConfig | None = None
    is_active: bool | None = None

class AutomationJobResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: str | None
    source_id: int
    template_ids: list[int]
    schedule: dict
    sync_config: dict
    processing_config: dict
    is_active: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    run_count: int
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class DryRunResult(BaseModel):
    job_id: int
    estimated_new_recordings: int
    estimated_matched_recordings: int
    templates_to_apply: list[int]
    estimated_duration_minutes: int
```

---

## 🔧 Core Logic

### File: `api/helpers/schedule_converter.py`

```python
from croniter import croniter
from datetime import datetime, timedelta
import pytz

def validate_min_interval(cron_expression: str, min_hours: int = 1) -> bool:
    """Validate that cron runs at least every min_hours"""
    try:
        base = datetime.now()
        cron = croniter(cron_expression, base)
        next_run = cron.get_next(datetime)
        following_run = cron.get_next(datetime)
        interval = (following_run - next_run).total_seconds() / 3600
        return interval >= min_hours
    except Exception:
        return False

def get_next_run_time(cron_expression: str, timezone_str: str) -> datetime:
    """Calculate next run time for cron in timezone"""
    tz = pytz.timezone(timezone_str)
    now = datetime.now(tz)
    cron = croniter(cron_expression, now)
    return cron.get_next(datetime)

def schedule_to_cron(schedule: dict) -> tuple[str, str]:
    """
    Convert schedule dict to (cron_expression, human_readable)
    """
    from api.schemas.automation.schedule import (
        TimeOfDaySchedule, HoursSchedule, WeekdaysSchedule, CronSchedule
    )
    
    schedule_type = schedule.get("type")
    
    if schedule_type == "time_of_day":
        obj = TimeOfDaySchedule(**schedule)
    elif schedule_type == "hours":
        obj = HoursSchedule(**schedule)
    elif schedule_type == "weekdays":
        obj = WeekdaysSchedule(**schedule)
    elif schedule_type == "cron":
        obj = CronSchedule(**schedule)
    else:
        raise ValueError(f"Unknown schedule type: {schedule_type}")
    
    return obj.to_cron(), obj.human_readable()
```

---

### File: `api/repositories/automation_repos.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from database.automation_models import AutomationJobModel
from datetime import datetime

class AutomationJobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create(self, job_data: dict, user_id: int) -> AutomationJobModel:
        job = AutomationJobModel(**job_data, user_id=user_id, created_at=datetime.utcnow(), updated_at=datetime.utcnow())
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job
    
    async def get_by_id(self, job_id: int, user_id: int) -> AutomationJobModel | None:
        stmt = select(AutomationJobModel).where(
            and_(AutomationJobModel.id == job_id, AutomationJobModel.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_user_jobs(self, user_id: int, active_only: bool = False) -> list[AutomationJobModel]:
        stmt = select(AutomationJobModel).where(AutomationJobModel.user_id == user_id)
        if active_only:
            stmt = stmt.where(AutomationJobModel.is_active == True)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def count_user_jobs(self, user_id: int) -> int:
        stmt = select(AutomationJobModel).where(AutomationJobModel.user_id == user_id)
        result = await self.session.execute(stmt)
        return len(list(result.scalars().all()))
    
    async def update(self, job: AutomationJobModel, updates: dict) -> AutomationJobModel:
        for key, value in updates.items():
            if value is not None:
                setattr(job, key, value)
        job.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(job)
        return job
    
    async def delete(self, job: AutomationJobModel):
        await self.session.delete(job)
        await self.session.commit()
    
    async def mark_run(self, job: AutomationJobModel, next_run_at: datetime):
        job.last_run_at = datetime.utcnow()
        job.next_run_at = next_run_at
        job.run_count += 1
        await self.session.commit()
```

---

### File: `api/services/automation_service.py`

```python
from sqlalchemy.ext.asyncio import AsyncSession
from api.repositories.automation_repos import AutomationJobRepository
from api.repositories.auth_repos import UserQuotasRepository
from api.helpers.schedule_converter import validate_min_interval, get_next_run_time, schedule_to_cron
from fastapi import HTTPException

class AutomationService:
    def __init__(self, session: AsyncSession, user_id: int):
        self.session = session
        self.user_id = user_id
        self.job_repo = AutomationJobRepository(session)
        self.quota_repo = UserQuotasRepository(session)
    
    async def validate_quota(self):
        quota = await self.quota_repo.get(self.user_id)
        current_count = await self.job_repo.count_user_jobs(self.user_id)
        
        if current_count >= quota.max_automation_jobs:
            raise HTTPException(
                status_code=400,
                detail=f"Automation job limit reached ({quota.max_automation_jobs})"
            )
        
        return quota
    
    async def validate_schedule(self, schedule: dict, quota):
        cron_expr, _ = schedule_to_cron(schedule)
        
        if not validate_min_interval(cron_expr, quota.min_automation_interval_hours):
            raise HTTPException(
                status_code=400,
                detail=f"Schedule interval must be at least {quota.min_automation_interval_hours} hour(s)"
            )
    
    async def create_job(self, job_data: dict):
        quota = await self.validate_quota()
        await self.validate_schedule(job_data["schedule"], quota)
        
        cron_expr, human = schedule_to_cron(job_data["schedule"])
        timezone = job_data["schedule"].get("timezone", "Europe/Moscow")
        next_run = get_next_run_time(cron_expr, timezone)
        
        job_data["next_run_at"] = next_run
        
        return await self.job_repo.create(job_data, self.user_id)
```

---

## ⚙️ Celery Integration

### File: `api/tasks/automation.py`

```python
from api.celery_app import celery_app
from database.manager import DatabaseManager
from api.repositories.automation_repos import AutomationJobRepository
from api.repositories.template_repos import RecordingTemplateRepository, RecordingRepository
from api.helpers.schedule_converter import get_next_run_time, schedule_to_cron
import logging

logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="automation.run_job")
def run_automation_job(self, job_id: int, user_id: int):
    """
    Execute automation job:
    1. Sync source
    2. Match recordings with templates
    3. Run full pipeline for matched recordings
    """
    async def _run():
        db_manager = DatabaseManager()
        async with db_manager.get_session() as session:
            job_repo = AutomationJobRepository(session)
            job = await job_repo.get_by_id(job_id, user_id)
            
            if not job or not job.is_active:
                logger.warning(f"Job {job_id} not found or inactive")
                return
            
            try:
                # 1. Sync source
                from api.routers.input_sources import sync_source
                sync_result = await sync_source(job.source_id, session, user_id)
                
                # 2. Get newly synced recordings (INITIALIZED)
                recording_repo = RecordingRepository(session)
                new_recordings = await recording_repo.get_by_status(
                    user_id=user_id,
                    status="INITIALIZED"
                )
                
                # 3. Match with templates (first match by priority)
                template_repo = RecordingTemplateRepository(session)
                template_ids = job.template_ids if job.template_ids else None
                
                for recording in new_recordings:
                    matched_template = await template_repo.match_recording(
                        recording, template_ids
                    )
                    if matched_template:
                        # 4. Run full pipeline
                        from api.tasks.processing import full_pipeline_task
                        full_pipeline_task.delay(
                            recording_id=recording.id,
                            user_id=user_id,
                            auto_upload=job.processing_config.get("auto_upload", True)
                        )
                
                # 5. Update job stats
                cron_expr, _ = schedule_to_cron(job.schedule)
                timezone = job.schedule.get("timezone", "Europe/Moscow")
                next_run = get_next_run_time(cron_expr, timezone)
                await job_repo.mark_run(job, next_run)
                
                logger.info(f"Job {job_id} completed. Processed {len(new_recordings)} recordings")
                
            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}")
                raise
    
    import asyncio
    asyncio.run(_run())

@celery_app.task(name="automation.dry_run")
def dry_run_automation_job(job_id: int, user_id: int):
    """Preview what the job would do without executing"""
    # Similar to run_automation_job but only counts, no execution
    pass
```

---

### Update: `api/celery_app.py`

```python
from celery import Celery
from celery_sqlalchemy_scheduler.schedulers import DatabaseScheduler
from api.config import settings

celery_app = Celery("zoomuploader")

celery_app.conf.update(
    broker_url=settings.REDIS_URL,
    result_backend=settings.REDIS_URL,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Celery Beat with SQLAlchemy scheduler
    beat_scheduler=DatabaseScheduler,
    beat_dburi=settings.DATABASE_URL,
)

celery_app.autodiscover_tasks(["api.tasks"])
```

---

## 🌐 API Endpoints

### File: `api/routers/automation.py`

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.core.dependencies import get_service_context
from api.schemas.automation.job import (
    AutomationJobCreate, AutomationJobUpdate, AutomationJobResponse, DryRunResult
)
from api.services.automation_service import AutomationService
from api.repositories.automation_repos import AutomationJobRepository
from api.tasks.automation import run_automation_job, dry_run_automation_job

router = APIRouter(prefix="/automation/jobs", tags=["Automation"])

@router.get("", response_model=list[AutomationJobResponse])
async def list_jobs(
    active_only: bool = Query(False),
    ctx = Depends(get_service_context)
):
    """List user's automation jobs"""
    repo = AutomationJobRepository(ctx.session)
    jobs = await repo.get_user_jobs(ctx.user_id, active_only)
    return jobs

@router.post("", response_model=AutomationJobResponse, status_code=201)
async def create_job(
    data: AutomationJobCreate,
    ctx = Depends(get_service_context)
):
    """Create new automation job"""
    service = AutomationService(ctx.session, ctx.user_id)
    job = await service.create_job(data.model_dump())
    
    # Sync with Celery Beat
    from api.helpers.beat_sync import sync_job_to_beat
    await sync_job_to_beat(job)
    
    return job

@router.get("/{job_id}", response_model=AutomationJobResponse)
async def get_job(
    job_id: int,
    ctx = Depends(get_service_context)
):
    """Get automation job details"""
    repo = AutomationJobRepository(ctx.session)
    job = await repo.get_by_id(job_id, ctx.user_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@router.patch("/{job_id}", response_model=AutomationJobResponse)
async def update_job(
    job_id: int,
    data: AutomationJobUpdate,
    ctx = Depends(get_service_context)
):
    """Update automation job"""
    repo = AutomationJobRepository(ctx.session)
    job = await repo.get_by_id(job_id, ctx.user_id)
    if not job:
        raise HTTPException(404, "Job not found")
    
    updates = data.model_dump(exclude_unset=True)
    
    if "schedule" in updates:
        service = AutomationService(ctx.session, ctx.user_id)
        quota = await service.quota_repo.get(ctx.user_id)
        await service.validate_schedule(updates["schedule"], quota)
    
    job = await repo.update(job, updates)
    
    # Re-sync with Celery Beat
    from api.helpers.beat_sync import sync_job_to_beat
    await sync_job_to_beat(job)
    
    return job

@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: int,
    ctx = Depends(get_service_context)
):
    """Delete automation job"""
    repo = AutomationJobRepository(ctx.session)
    job = await repo.get_by_id(job_id, ctx.user_id)
    if not job:
        raise HTTPException(404, "Job not found")
    
    await repo.delete(job)
    
    # Remove from Celery Beat
    from api.helpers.beat_sync import remove_job_from_beat
    await remove_job_from_beat(job_id)

@router.post("/{job_id}/run")
async def trigger_job(
    job_id: int,
    dry_run: bool = Query(False),
    ctx = Depends(get_service_context)
):
    """Manually trigger automation job"""
    repo = AutomationJobRepository(ctx.session)
    job = await repo.get_by_id(job_id, ctx.user_id)
    if not job:
        raise HTTPException(404, "Job not found")
    
    if dry_run:
        task = dry_run_automation_job.delay(job_id, ctx.user_id)
        return {"task_id": task.id, "mode": "dry_run"}
    else:
        task = run_automation_job.delay(job_id, ctx.user_id)
        return {"task_id": task.id, "mode": "execute"}
```

---

### File: `api/helpers/beat_sync.py`

```python
from celery_sqlalchemy_scheduler.models import PeriodicTask, CrontabSchedule
from database.automation_models import AutomationJobModel
from api.helpers.schedule_converter import schedule_to_cron
from sqlalchemy.ext.asyncio import AsyncSession

async def sync_job_to_beat(job: AutomationJobModel):
    """Sync automation job to Celery Beat"""
    cron_expr, _ = schedule_to_cron(job.schedule)
    minute, hour, day, month, day_of_week = cron_expr.split()
    
    # Create or update CrontabSchedule
    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute=minute,
        hour=hour,
        day_of_month=day,
        month_of_year=month,
        day_of_week=day_of_week,
        timezone=job.schedule.get("timezone", "UTC")
    )
    
    # Create or update PeriodicTask
    task, created = PeriodicTask.objects.update_or_create(
        name=f"automation_job_{job.id}",
        defaults={
            "task": "automation.run_job",
            "crontab": schedule,
            "args": [job.id, job.user_id],
            "enabled": job.is_active
        }
    )
    
    return task

async def remove_job_from_beat(job_id: int):
    """Remove job from Celery Beat"""
    try:
        task = PeriodicTask.objects.get(name=f"automation_job_{job_id}")
        task.delete()
    except PeriodicTask.DoesNotExist:
        pass
```

---

## 📦 Dependencies

### Update: `requirements.txt`

```txt
# ... existing dependencies ...

# Automation
celery-sqlalchemy-scheduler==0.4.0
croniter==2.0.1
pytz==2024.1
```

---

## 🔨 Makefile Commands

### Update: `Makefile`

```makefile
# ... existing commands ...

## Celery Beat
celery-beat:
	celery -A api.celery_app beat --loglevel=info

## Run worker + beat (development)
celery-dev:
	celery -A api.celery_app worker --beat --loglevel=info
```

---

## ✅ Testing Checklist

### Manual Testing

```bash
# 1. Create automation job
curl -X POST http://localhost:8000/api/v1/automation/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily Zoom Sync",
    "source_id": 1,
    "template_ids": [],
    "schedule": {
      "type": "time_of_day",
      "time": "06:00",
      "timezone": "Europe/Moscow"
    }
  }'

# 2. Dry run
curl -X POST http://localhost:8000/api/v1/automation/jobs/1/run?dry_run=true \
  -H "Authorization: Bearer $TOKEN"

# 3. List jobs
curl http://localhost:8000/api/v1/automation/jobs \
  -H "Authorization: Bearer $TOKEN"

# 4. Update job
curl -X PATCH http://localhost:8000/api/v1/automation/jobs/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"is_active": false}'

# 5. Delete job
curl -X DELETE http://localhost:8000/api/v1/automation/jobs/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

## 📝 Implementation Order

1. ✅ Phase 1: Database (migrations 012, 013, 014)
2. ✅ Phase 2: Models & Schemas
3. ✅ Phase 3: Core Logic (helpers, repos, service)
4. ✅ Phase 4: Celery (tasks, beat setup, sync)
5. ✅ Phase 5: API (router, endpoints)
6. ✅ Phase 6: Testing & Docs

---

## 🎯 Success Criteria

- [ ] User can create automation job via API
- [ ] Schedule validates min 1 hour interval
- [ ] Max 5 jobs per user enforced
- [ ] Celery Beat picks up jobs from database
- [ ] Job runs on schedule and syncs + processes recordings
- [ ] Dry-run mode works without side effects
- [ ] Jobs can be updated/deleted and Beat syncs
- [ ] All endpoints documented in Swagger
- [ ] Zero linter errors
- [ ] Use numbered migration names (001_<...>)

---

**Ready to implement! Following this plan step by step.**

