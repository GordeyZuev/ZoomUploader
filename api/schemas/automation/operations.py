"""Schemas for automation operations."""

from pydantic import BaseModel


class TriggerJobResponse(BaseModel):
    """Результат запуска automation job."""

    task_id: str
    mode: str  # "dry_run" | "execute"
    message: str
