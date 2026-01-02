"""Схемы ответов для recordings."""

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


class OutputTargetResponse(BaseModel):
    """Целевая платформа."""

    id: int
    target_type: TargetType
    status: TargetStatus
    target_meta: dict[str, Any] = Field(default_factory=dict)
    uploaded_at: datetime | None = None


class ProcessingStageResponse(BaseModel):
    """Этап обработки."""

    stage_type: str
    status: str
    failed: bool
    failed_at: datetime | None = None
    failed_reason: str | None = None
    retry_count: int = 0
    completed_at: datetime | None = None


class RecordingResponse(BaseModel):
    """Ответ с записью."""

    id: int
    display_name: str
    start_time: datetime
    duration: int
    status: ProcessingStatus
    is_mapped: bool
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
    """Ответ со списком записей."""

    items: list[RecordingResponse]


class ProcessRecordingResponse(BaseModel):
    """Ответ на запрос обработки."""

    message: str
    recording_id: int
    status: ProcessingStatus
    estimated_time: int | None = Field(None, description="Оценка времени в секундах")
