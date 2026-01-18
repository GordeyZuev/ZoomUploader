"""Recording template schemas (fully typed)"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from api.schemas.common import BASE_MODEL_CONFIG, ORM_MODEL_CONFIG

from .matching_rules import MatchingRules
from .metadata_config import TemplateMetadataConfig
from .output_config import TemplateOutputConfig
from .processing_config import TemplateProcessingConfig

# ============================================================================
# Recording Template Schemas (Fully Typed)
# ============================================================================


class RecordingTemplateBase(BaseModel):
    """Базовая схема для шаблона с полной типизацией."""

    model_config = BASE_MODEL_CONFIG

    name: str = Field(..., min_length=3, max_length=255, description="Название шаблона")
    description: str | None = Field(None, max_length=1000, description="Описание шаблона")

    # Типизированные конфигурации
    matching_rules: MatchingRules | None = Field(
        None,
        description="Правила сопоставления recordings с template",
    )
    processing_config: TemplateProcessingConfig | None = Field(
        None,
        description="Настройки обработки: transcription, topics, subtitles",
    )
    metadata_config: TemplateMetadataConfig | None = Field(
        None,
        description="Content metadata: title_template, playlist_id",
    )
    output_config: TemplateOutputConfig | None = Field(
        None,
        description="Output настройки: preset_ids, auto_upload",
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


class RecordingTemplateCreate(RecordingTemplateBase):
    """Схема для создания шаблона (полностью типизированная)."""

    is_draft: bool = Field(False, description="Черновик (не применяется автоматически)")

    @model_validator(mode="after")
    def validate_template(self) -> "RecordingTemplateCreate":
        """Кросс-валидация template."""
        # Если не draft, должны быть matching_rules
        if not self.is_draft:
            if not self.matching_rules:
                raise ValueError("Non-draft template требует matching_rules")

            # Проверим что есть хоть одно правило
            rules = self.matching_rules
            has_rule = (
                (rules.exact_matches and len(rules.exact_matches) > 0)
                or (rules.keywords and len(rules.keywords) > 0)
                or (rules.patterns and len(rules.patterns) > 0)
                or (rules.source_ids and len(rules.source_ids) > 0)
            )

            if not has_rule:
                raise ValueError(
                    "matching_rules должны содержать хоть одно правило (exact_matches, keywords, patterns или source_ids)"
                )

        # Если есть output_config с auto_upload=True, нужен processing_config
        if self.output_config and self.output_config.auto_upload:
            if not self.processing_config:
                raise ValueError("auto_upload=True требует processing_config")

        # Если есть metadata_config с title_template, должен быть output_config
        if self.metadata_config and self.metadata_config.title_template:
            if not self.output_config:
                raise ValueError("title_template требует output_config с preset_ids")

        return self


class RecordingTemplateUpdate(BaseModel):
    """Схема для обновления шаблона (полностью типизированная)."""

    name: str | None = Field(None, min_length=3, max_length=255)
    description: str | None = Field(None, max_length=1000)
    matching_rules: MatchingRules | None = None
    processing_config: TemplateProcessingConfig | None = None
    metadata_config: TemplateMetadataConfig | None = None
    output_config: TemplateOutputConfig | None = None
    is_draft: bool | None = None
    is_active: bool | None = None


class RecordingTemplateResponse(RecordingTemplateBase):
    """Схема ответа для шаблона."""

    # ORM модель - используем специальную конфигурацию
    model_config = ORM_MODEL_CONFIG

    id: int
    user_id: int
    is_draft: bool
    is_active: bool
    used_count: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RecordingTemplateListResponse(BaseModel):
    """Схема для списка шаблонов."""

    # ORM модель - используем специальную конфигурацию
    model_config = ORM_MODEL_CONFIG

    id: int
    name: str
    description: str | None
    is_draft: bool
    is_active: bool
    used_count: int
    created_at: datetime
    updated_at: datetime
