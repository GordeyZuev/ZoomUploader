"""Схемы для health check endpoints."""

from pydantic import BaseModel

from .config import BASE_MODEL_CONFIG


class HealthCheckResponse(BaseModel):
    """Health check ответ."""

    model_config = BASE_MODEL_CONFIG

    status: str
    service: str
