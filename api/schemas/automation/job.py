"""Schemas for automation job CRUD operations."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .schedule import Schedule


class SyncConfig(BaseModel):
    """Configuration for source synchronization."""

    sync_days: int = Field(default=2, ge=1, le=30, description="Sync recordings from last N days")
    allow_skipped: bool = Field(default=False, description="Allow processing SKIPPED recordings")


class ProcessingConfig(BaseModel):
    """Configuration for recording processing."""

    auto_process: bool = Field(default=True, description="Automatically process matched recordings")
    auto_upload: bool = Field(default=True, description="Automatically upload after processing")
    max_parallel: int = Field(default=3, ge=1, le=10, description="Max parallel processing tasks")


class AutomationJobCreate(BaseModel):
    """Schema for creating new automation job."""

    name: str = Field(min_length=1, max_length=200, description="Job name")
    description: str | None = Field(default=None, description="Job description")
    source_id: int = Field(description="Input source ID to sync")
    template_ids: list[int] = Field(default_factory=list, description="Template IDs to apply (empty = all active)")
    schedule: Schedule = Field(description="Schedule configuration")
    sync_config: SyncConfig = Field(default_factory=SyncConfig, description="Sync configuration")
    processing_config: ProcessingConfig = Field(
        default_factory=ProcessingConfig, description="Processing configuration"
    )


class AutomationJobUpdate(BaseModel):
    """Schema for updating automation job."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    template_ids: list[int] | None = None
    schedule: Schedule | None = None
    sync_config: SyncConfig | None = None
    processing_config: ProcessingConfig | None = None
    is_active: bool | None = None


class AutomationJobResponse(BaseModel):
    """Schema for automation job response."""

    model_config = ConfigDict(from_attributes=True)

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


class DryRunResult(BaseModel):
    """Result of dry-run preview."""

    job_id: int
    estimated_new_recordings: int = Field(description="Estimated number of new recordings to sync")
    estimated_matched_recordings: int = Field(description="Estimated number of recordings that will match templates")
    templates_to_apply: list[int] = Field(description="Template IDs that will be applied")
    estimated_duration_minutes: int = Field(description="Estimated total duration in minutes")
