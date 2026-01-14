"""Output preset schemas (fully typed)"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG, ORM_MODEL_CONFIG

from .preset_metadata import VKPresetMetadata, YouTubePresetMetadata

# ============================================================================
# Output Preset Schemas (Fully Typed)
# ============================================================================


class OutputPresetBase(BaseModel):
    """Базовая схема для пресета с полной типизацией."""

    model_config = BASE_MODEL_CONFIG

    name: str = Field(..., min_length=1, max_length=255, description="Название пресета")
    description: str | None = Field(None, max_length=1000, description="Описание пресета")
    platform: Literal["youtube", "vk"] = Field(..., description="Платформа (youtube или vk)")

    preset_metadata: YouTubePresetMetadata | VKPresetMetadata = Field(
        ...,
        description="Платформо-специфичные настройки",
    )

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: str) -> str:
        """Очистка названия от пробелов."""
        if isinstance(v, str):
            v = v.strip()
            if not v:
                raise ValueError("Название не может быть пустым")
        return v


class OutputPresetCreate(OutputPresetBase):
    """Схема для создания пресета (полностью типизированная)."""

    credential_id: int = Field(..., gt=0, description="ID credentials для этой платформы")


class OutputPresetUpdate(BaseModel):
    """Схема для обновления пресета (полностью типизированная)."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    credential_id: int | None = Field(None, gt=0)
    preset_metadata: YouTubePresetMetadata | VKPresetMetadata | None = None
    is_active: bool | None = None


class OutputPresetResponse(OutputPresetBase):
    """Схема ответа для пресета."""

    model_config = ORM_MODEL_CONFIG

    id: int
    user_id: int
    credential_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
