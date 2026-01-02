"""Схемы фильтров для recordings."""

from pydantic import BaseModel, Field

from models import ProcessingStatus


class RecordingFilters(BaseModel):
    """Фильтры для списка записей."""

    status: ProcessingStatus | None = Field(None, description="Фильтр по статусу")
    failed: bool | None = Field(None, description="Фильтр по наличию ошибки")
    source_type: str | None = Field(None, description="Фильтр по типу источника")
    from_date: str | None = Field(None, description="Фильтр по дате начала (ISO 8601)")
    to_date: str | None = Field(None, description="Фильтр по дате окончания (ISO 8601)")
