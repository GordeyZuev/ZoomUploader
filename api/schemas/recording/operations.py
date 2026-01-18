"""Schemas for recording operations endpoints."""

from pydantic import BaseModel


class DryRunResponse(BaseModel):
    """Result of dry-run check for single recording."""

    dry_run: bool = True
    recording_id: int | None = None
    steps: list[dict] | None = None


class RecordingOperationResponse(BaseModel):
    """Result of operation over recording."""

    success: bool
    recording_id: int | None = None
    message: str | None = None
    task_id: str | None = None


class RecordingBulkOperationResponse(BaseModel):
    """Result of bulk operation."""

    queued_count: int
    skipped_count: int
    total: int | None = None
    tasks: list[dict]


class BulkProcessDryRunResponse(BaseModel):
    """
    Result of dry-run for bulk operation.
    """

    matched_count: int
    skipped_count: int
    total: int
    recordings: list[dict]


class RetryUploadResponse(BaseModel):
    """Result of retry upload."""

    message: str
    recording_id: int
    tasks: list[dict] | None = None


class MappingStatusResponse(BaseModel):
    """Status of mapping recording."""

    recording_id: int
    is_mapped: bool
    template_id: int | None = None
    template_name: str | None = None


class RecordingConfigResponse(BaseModel):
    """Full configuration for recording."""

    recording_id: int
    is_mapped: bool
    template_id: int | None = None
    template_name: str | None = None
    has_manual_override: bool = False
    processing_config: dict | None = None
    output_config: dict | None = None
    metadata_config: dict | None = None


class ConfigUpdateResponse(BaseModel):
    """Result of updating configuration."""

    recording_id: int
    message: str
    has_manual_override: bool
    overrides: dict | None = None
    effective_config: dict | None = None


class ConfigSaveResponse(BaseModel):
    """Result of saving configuration."""

    recording_id: int
    message: str
    has_manual_override: bool = False
    effective_config: dict | None = None


class TemplateInfoResponse(BaseModel):
    """Information about template."""

    template_id: int
    name: str
    description: str | None = None


class ResetRecordingResponse(BaseModel):
    """Result of recording reset operation."""

    success: bool
    recording_id: int
    message: str
    deleted_files: list[dict] | None = None
    errors: list[dict] | None = None
    status: str | None = None
    preserved: dict | None = None
    task_id: str | None = None
