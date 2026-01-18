"""Pydantic схемы для квот пользователей."""

from datetime import datetime

from pydantic import BaseModel, Field


class UserQuotaBase(BaseModel):
    """Базовая схема квот."""

    max_recordings_per_month: int = Field(100, ge=0, description="Макс. записей в месяц")
    max_storage_gb: int = Field(50, ge=0, description="Макс. место на диске (GB)")
    max_concurrent_tasks: int = Field(3, ge=1, description="Макс. одновременных задач")


class UserQuotaCreate(UserQuotaBase):
    """Схема для создания квот."""

    user_id: int


class UserQuotaUpdate(BaseModel):
    """Схема для обновления квот."""

    max_recordings_per_month: int | None = Field(None, ge=0)
    max_storage_gb: int | None = Field(None, ge=0)
    max_concurrent_tasks: int | None = Field(None, ge=1)
    current_recordings_count: int | None = Field(None, ge=0)
    current_storage_gb: float | None = Field(None, ge=0)
    current_tasks_count: int | None = Field(None, ge=0)
    quota_reset_at: datetime | None = None


class UserQuotaInDB(UserQuotaBase):
    """Схема квот в БД."""

    id: int
    user_id: int
    current_recordings_count: int = 0
    current_storage_gb: float = 0.0
    current_tasks_count: int = 0
    quota_reset_at: datetime
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserQuotaResponse(BaseModel):
    """Схема ответа с квотами."""

    max_recordings_per_month: int
    max_storage_gb: int
    max_concurrent_tasks: int
    current_recordings_count: int
    current_storage_gb: float
    current_tasks_count: int
    quota_reset_at: datetime

    class Config:
        from_attributes = True
