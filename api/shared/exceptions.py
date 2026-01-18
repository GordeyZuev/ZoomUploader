"""Custom API exceptions"""

from fastapi import HTTPException, status


class APIException(HTTPException):
    """Базовое исключение для API."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)


class NotFoundError(APIException):
    """Ресурс не найден."""

    def __init__(self, resource: str, resource_id: int | str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} with id {resource_id} not found",
        )


class ValidationError(APIException):
    """Ошибка валидации."""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        )


class ConflictError(APIException):
    """Конфликт данных."""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )


# Exceptions for Celery tasks (not HTTP-related)
class TaskError(Exception):
    """Базовое исключение для Celery задач."""


class CredentialError(TaskError):
    """Ошибка валидации credentials (токен невалиден, истек и т.д.)."""

    def __init__(self, platform: str, reason: str):
        self.platform = platform
        self.reason = reason
        super().__init__(f"Credential error for {platform}: {reason}")


class ResourceNotFoundError(TaskError):
    """Ресурс не найден (например, файл для загрузки)."""

    def __init__(self, resource_type: str, resource_id: int | str):
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} {resource_id} not found")
