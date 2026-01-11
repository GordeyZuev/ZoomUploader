"""Схемы для пресетов выгрузки."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class OutputPresetBase(BaseModel):
    """Базовая схема для пресета."""

    name: str = Field(..., min_length=1, max_length=255, description="Название пресета")
    description: str | None = Field(None, max_length=1000, description="Описание пресета")
    platform: Literal["youtube", "vk", "rutube", "gdrive", "yandex_disk"] = Field(..., description="Платформа")
    preset_metadata: dict[str, Any] | None = Field(None, description="Метаданные пресета")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Валидация названия пресета."""
        v = v.strip()
        if not v:
            raise ValueError("Название не может быть пустым")
        return v

    @field_validator("preset_metadata")
    @classmethod
    def validate_metadata(cls, v: dict[str, Any] | None, info) -> dict[str, Any] | None:
        """Валидация метаданных в зависимости от платформы."""
        if v is None:
            return {}

        platform = info.data.get("platform")

        # Validate topics_display configuration (platform-agnostic)
        if "topics_display" in v and v["topics_display"] is not None:
            topics_cfg = v["topics_display"]

            # Validate format
            if "format" in topics_cfg:
                valid_formats = ["numbered_list", "bullet_list", "dash_list", "comma_separated", "inline"]
                if topics_cfg["format"] not in valid_formats:
                    raise ValueError(f"topics_display.format должен быть одним из: {', '.join(valid_formats)}")

            # Validate max_count (None = unlimited)
            if "max_count" in topics_cfg:
                max_count = topics_cfg["max_count"]
                if max_count is not None and (not isinstance(max_count, int) or max_count < 1):
                    raise ValueError("topics_display.max_count должен быть положительным числом или null (безлимит)")

            # Validate lengths
            if "min_length" in topics_cfg:
                min_len = topics_cfg["min_length"]
                if not isinstance(min_len, int) or min_len < 0:
                    raise ValueError("topics_display.min_length должен быть неотрицательным числом")

            if "max_length" in topics_cfg:
                max_len = topics_cfg["max_length"]
                if not isinstance(max_len, int) or max_len < 1:
                    raise ValueError("topics_display.max_length должен быть положительным числом")

            # Check min_length < max_length
            if "min_length" in topics_cfg and "max_length" in topics_cfg:
                if topics_cfg["min_length"] >= topics_cfg["max_length"]:
                    raise ValueError("topics_display.min_length должен быть меньше max_length")

        platform = info.data.get("platform")

        if platform == "youtube":
            # Validate YouTube-specific fields
            if "privacy" in v and v["privacy"] not in ["private", "public", "unlisted"]:
                raise ValueError("privacy должен быть: private, public или unlisted")

            # Legacy support
            if "privacyStatus" in v and v["privacyStatus"] not in ["private", "public", "unlisted"]:
                raise ValueError("privacyStatus должен быть: private, public или unlisted")

            if "category_id" in v:
                try:
                    cat_id = int(v["category_id"])
                    if cat_id < 1:
                        raise ValueError("category_id должен быть положительным числом")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный category_id: {e}") from e

            # Legacy support
            if "categoryId" in v:
                try:
                    cat_id = int(v["categoryId"])
                    if cat_id < 1:
                        raise ValueError("categoryId должен быть положительным числом")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный categoryId: {e}") from e

            # Validate publishAt format if provided
            if "publish_at" in v and v["publish_at"] is not None:
                if not isinstance(v["publish_at"], str):
                    raise ValueError("publish_at должен быть строкой в формате ISO 8601")
                # Basic ISO format check (will be parsed by YouTube API)
                if not v["publish_at"].endswith("Z") and "+" not in v["publish_at"]:
                    raise ValueError("publish_at должен быть в формате ISO 8601 с timezone (Z или +00:00)")

            # Validate tags
            if "tags" in v and v["tags"] is not None:
                if not isinstance(v["tags"], list):
                    raise ValueError("tags должен быть массивом строк")
                if len(v["tags"]) > 500:
                    raise ValueError("Максимум 500 тегов для YouTube")

        elif platform == "vk":
            # Validate VK-specific fields
            if "group_id" in v:
                try:
                    group_id = int(v["group_id"])
                    if group_id < 0:
                        raise ValueError("group_id должен быть положительным")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный group_id: {e}") from e

            if "album_id" in v and v["album_id"] is not None:
                try:
                    album_id = int(v["album_id"])
                    if album_id < 0:
                        raise ValueError("album_id должен быть положительным")
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Неверный album_id: {e}") from e

            # Validate privacy settings
            if "privacy_view" in v and v["privacy_view"] not in [0, 1, 2, 3]:
                raise ValueError("privacy_view должен быть 0-3 (0=все, 1=друзья, 2=друзья друзей, 3=только я)")

            if "privacy_comment" in v and v["privacy_comment"] not in [0, 1, 2, 3]:
                raise ValueError("privacy_comment должен быть 0-3")

        return v


class OutputPresetCreate(OutputPresetBase):
    """Схема для создания пресета."""

    credential_id: int = Field(..., description="ID credentials")


class OutputPresetUpdate(BaseModel):
    """Схема для обновления пресета."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    credential_id: int | None = None
    preset_metadata: dict[str, Any] | None = None
    is_active: bool | None = None


class OutputPresetResponse(OutputPresetBase):
    """Схема ответа для пресета."""

    id: int
    user_id: int
    credential_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

