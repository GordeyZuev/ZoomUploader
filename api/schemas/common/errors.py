"""Схемы для ошибок."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Стандартный ответ с ошибкой."""

    error: str
    detail: str | list[dict] | None = None


class ValidationErrorResponse(BaseModel):
    """Ответ с ошибками валидации."""

    error: str = "Validation error"
    detail: list[dict]
