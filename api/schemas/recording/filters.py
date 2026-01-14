"""Схемы фильтров для recordings."""

from pydantic import BaseModel, Field


class RecordingFilters(BaseModel):
    """
    Фильтры для bulk операций над recordings.

    Поддерживает фильтрацию по различным критериям для автоматической выборки записей.
    """

    # Связи
    template_id: int | None = Field(None, description="Фильтр по ID шаблона")
    source_id: int | None = Field(None, alias="input_source_id", description="Фильтр по ID источника")

    # Статусы (множественный выбор)
    status: list[str] | None = Field(None, description="Фильтр по статусам (список)")

    # Флаги
    is_mapped: bool | None = Field(None, description="Фильтр по наличию mapping к template")
    failed: bool | None = Field(None, description="Фильтр по наличию ошибки")
    exclude_blank: bool = Field(True, description="Исключить blank records (слишком короткие/маленькие)")

    # Даты (для обратной совместимости)
    from_date: str | None = Field(None, description="Фильтр по дате начала (ISO 8601)")
    to_date: str | None = Field(None, description="Фильтр по дате окончания (ISO 8601)")
    source_type: str | None = Field(None, description="Фильтр по типу источника")

    # Сортировка
    order_by: str = Field("created_at", description="Поле для сортировки (created_at, updated_at, id)")
    order: str = Field("asc", description="Направление сортировки (asc, desc)")

    class Config:
        json_schema_extra = {
            "example": {
                "template_id": 5,
                "status": ["INITIALIZED", "FAILED"],
                "is_mapped": True,
                "exclude_blank": True,
                "order_by": "created_at",
                "order": "asc"
            }
        }
