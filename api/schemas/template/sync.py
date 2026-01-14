"""Schemas for input source sync operations."""

from pydantic import BaseModel


class SyncSourceResponse(BaseModel):
    """Результат синхронизации источника."""

    status: str  # "success" | "error"
    recordings_found: int | None = None
    recordings_saved: int | None = None
    recordings_updated: int | None = None
    error: str | None = None


class SyncTaskResponse(BaseModel):
    """Результат постановки sync в очередь."""

    task_id: str
    status: str
    message: str | None = None
