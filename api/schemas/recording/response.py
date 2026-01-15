"""Recording response schemas"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from api.schemas.common.pagination import PaginatedResponse
from models import ProcessingStatus, SourceType, TargetStatus, TargetType


class SourceResponse(BaseModel):
    """Источник записи."""

    source_type: SourceType
    source_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PresetInfo(BaseModel):
    """Output preset information."""

    id: int
    name: str


class OutputTargetResponse(BaseModel):
    """Целевая платформа."""

    id: int
    target_type: TargetType
    status: TargetStatus
    target_meta: dict[str, Any] = Field(default_factory=dict)
    uploaded_at: datetime | None = None
    failed: bool = False
    failed_at: datetime | None = None
    failed_reason: str | None = None
    retry_count: int = 0
    preset: PresetInfo | None = None


class ProcessingStageResponse(BaseModel):
    """Этап обработки."""

    stage_type: str
    status: str
    failed: bool
    failed_at: datetime | None = None
    failed_reason: str | None = None
    retry_count: int = 0
    completed_at: datetime | None = None


class SourceInfo(BaseModel):
    """Source information for list view."""

    type: SourceType
    name: str | None = None
    input_source_id: int | None = None


class UploadInfo(BaseModel):
    """Upload information for single platform."""

    status: str
    url: str | None = None
    uploaded_at: datetime | None = None
    error: str | None = None


class RecordingListItem(BaseModel):
    """Recording item for list view (optimized for UI table)."""

    id: int
    display_name: str
    start_time: datetime
    duration: int
    status: ProcessingStatus
    failed: bool
    failed_at_stage: str | None = None
    is_mapped: bool
    template_id: int | None = None
    template_name: str | None = None
    source: SourceInfo | None = None
    uploads: dict[str, UploadInfo] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class RecordingResponse(BaseModel):
    """Full recording response with all details."""

    id: int
    display_name: str
    start_time: datetime
    duration: int
    status: ProcessingStatus
    is_mapped: bool
    blank_record: bool = Field(False, description="Whether recording is too short/small to process")
    processing_preferences: dict[str, Any] | None = None
    source: SourceResponse | None = None
    outputs: list[OutputTargetResponse] = Field(default_factory=list)
    processing_stages: list[ProcessingStageResponse] = Field(default_factory=list)
    failed: bool = False
    failed_at: datetime | None = None
    failed_reason: str | None = None
    failed_at_stage: str | None = None
    video_file_size: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RecordingListResponse(PaginatedResponse):
    """Response with list of recordings (optimized for UI)."""

    items: list[RecordingListItem]


class ProcessRecordingResponse(BaseModel):
    """Ответ на запрос обработки."""

    message: str
    recording_id: int
    status: ProcessingStatus
    estimated_time: int | None = Field(None, description="Оценка времени в секундах")
