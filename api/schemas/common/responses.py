"""Базовые переиспользуемые response схемы."""

from pydantic import BaseModel

from .config import BASE_MODEL_CONFIG


class MessageResponse(BaseModel):
    """Простой ответ с сообщением."""

    model_config = BASE_MODEL_CONFIG

    message: str
    detail: str | None = None


class SuccessResponse(BaseModel):
    """Стандартный success ответ."""

    model_config = BASE_MODEL_CONFIG

    success: bool
    message: str | None = None


class TaskQueuedResponse(BaseModel):
    """Ответ при постановке задачи в очередь."""

    model_config = BASE_MODEL_CONFIG

    task_id: str
    status: str = "queued"
    message: str | None = None


class TaskInfo(BaseModel):
    """Информация о задаче в bulk операции."""

    model_config = BASE_MODEL_CONFIG

    task_id: str
    recording_id: int | None = None
    status: str = "queued"


class BulkOperationResponse(BaseModel):
    """Результат массовой операции."""

    model_config = BASE_MODEL_CONFIG

    queued_count: int
    skipped_count: int
    total: int | None = None
    tasks: list[TaskInfo] | None = None
