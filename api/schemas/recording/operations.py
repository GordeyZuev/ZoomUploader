"""Schemas for recording operations endpoints."""

from pydantic import BaseModel


class DryRunResponse(BaseModel):
    """Результат dry-run проверки."""

    dry_run: bool = True
    recording_id: int | None = None
    matched_count: int | None = None
    recordings: list[dict] | None = None


class RecordingOperationResponse(BaseModel):
    """Результат операции над recording."""

    success: bool
    recording_id: int | None = None
    message: str | None = None
    task_id: str | None = None


class RecordingBulkOperationResponse(BaseModel):
    """Результат bulk операции."""

    queued_count: int
    skipped_count: int
    total: int | None = None
    tasks: list[dict]


class RetryUploadResponse(BaseModel):
    """Результат retry upload."""

    message: str
    recording_id: int
    tasks: list[dict] | None = None


class MappingStatusResponse(BaseModel):
    """Статус mapping recording."""

    recording_id: int
    is_mapped: bool
    template_id: int | None = None
    template_name: str | None = None


class ConfigSaveResponse(BaseModel):
    """Результат сохранения конфигурации."""

    recording_id: int
    message: str


class TemplateInfoResponse(BaseModel):
    """Информация о шаблоне."""

    template_id: int
    name: str
    description: str | None = None
