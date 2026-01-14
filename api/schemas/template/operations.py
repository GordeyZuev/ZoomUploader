"""Schemas for template operations endpoints."""

from pydantic import BaseModel


class BulkDeleteResponse(BaseModel):
    """Результат bulk delete."""

    template_id: int
    template_name: str
    deleted_recordings: int
    deleted_targets: int


class RematchTaskResponse(BaseModel):
    """Результат запуска re-match."""

    message: str
    task_id: str
    template_id: int | None = None
