"""Schemas for template operations endpoints."""

from pydantic import BaseModel


class BulkDeleteResponse(BaseModel):
    """Result of bulk delete."""

    template_id: int
    template_name: str
    deleted_recordings: int
    deleted_targets: int


class TemplateStatsResponse(BaseModel):
    """Template usage statistics."""

    template_id: int
    template_name: str
    total_recordings: int
    by_status: dict
    last_matched_at: str | None = None
    is_active: bool


class TemplatePreviewRecording(BaseModel):
    """Recording that will be matched in preview."""

    id: int
    display_name: str
    current_status: str
    current_is_mapped: bool
    will_become_status: str
    will_become_is_mapped: bool
    start_time: str
    duration: int | None = None
    input_source_id: int | None = None


class TemplatePreviewResponse(BaseModel):
    """Preview of template matching."""

    template_id: int
    template_name: str
    mode: str
    total_checked: int
    will_match_count: int
    will_match: list[TemplatePreviewRecording]
    note: str


class RematchTaskResponse(BaseModel):
    """Result of rematch task start."""

    message: str
    task_id: str
    template_id: int
    template_name: str
    only_unmapped: bool
    note: str
