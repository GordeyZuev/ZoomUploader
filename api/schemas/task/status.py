"""Схемы для статуса Celery задач."""

from pydantic import BaseModel, Field

from api.schemas.common import BASE_MODEL_CONFIG


class TaskProgressInfo(BaseModel):
    """Информация о прогрессе задачи."""

    model_config = BASE_MODEL_CONFIG

    status: str
    progress: int = Field(0, ge=0, le=100, description="Прогресс выполнения (0-100)")
    step: str | None = None


class TaskResult(BaseModel):
    """Результат выполнения задачи."""

    model_config = BASE_MODEL_CONFIG

    recording_id: int | None = None
    output_url: str | None = None
    file_path: str | None = None
    message: str | None = None

    # Дополнительные поля для разных типов задач
    transcription_text: str | None = None
    topics: list[str] | None = None
    duration_seconds: float | None = Field(None, ge=0, description="Длительность в секундах")


class TaskStatusResponse(BaseModel):
    """Статус Celery задачи."""

    model_config = BASE_MODEL_CONFIG

    task_id: str
    state: str
    status: str
    progress: int = Field(0, ge=0, le=100)
    result: TaskResult | dict | None = None  # dict для legacy support
    error: str | None = None


class TaskCancelResponse(BaseModel):
    """Результат отмены задачи."""

    model_config = BASE_MODEL_CONFIG

    task_id: str
    status: str
    message: str
