"""Типизированные схемы для template matching_rules."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import BASE_MODEL_CONFIG
from api.schemas.common.validators import clean_and_deduplicate_strings, validate_regex_patterns

# ============================================================================
# Matching Rules
# ============================================================================


class MatchingRules(BaseModel):
    """
    Правила сопоставления recordings с template.

    Поддерживает:
    - exact_matches: точное совпадение названия
    - keywords: поиск ключевых слов
    - patterns: regex паттерны
    - source_ids: привязка к конкретным источникам
    """

    model_config = BASE_MODEL_CONFIG

    # Точные совпадения
    exact_matches: list[str] | None = Field(
        None,
        description="Список точных совпадений названия",
        examples=[["Машинное обучение - лекция 1", "ML Lecture 1"]],
    )

    # Ключевые слова (OR логика)
    keywords: list[str] | None = Field(
        None,
        description="Ключевые слова для поиска (OR). Регистронезависимый поиск",
        examples=[["генеративные модели", "deep learning", "нейронные сети"]],
    )

    # Regex паттерны (OR логика)
    patterns: list[str] | None = Field(
        None,
        description="Regex паттерны для matching (OR)",
        examples=[
            ["^Лекция \\d+", "Временные ряды.*\\d{2}\\.\\d{2}"],
            ["ML-\\d{4}-\\d{2}-\\d{2}"],
        ],
    )

    # Привязка к источникам
    source_ids: list[int] | None = Field(
        None,
        description="ID источников (input_sources). Только для записей из этих источников",
        examples=[[1, 2, 3]],
    )

    # Логика комбинирования (AND по умолчанию)
    match_mode: Literal["any", "all"] = Field(
        "any",
        description="Режим matching: 'any' = OR (хоть одно правило), 'all' = AND (все правила)",
    )

    # Case sensitivity
    case_sensitive: bool = Field(False, description="Учитывать регистр при matching")

    @field_validator("exact_matches")
    @classmethod
    def validate_exact_matches(cls, v: list[str] | None) -> list[str] | None:
        return clean_and_deduplicate_strings(v)

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, v: list[str] | None) -> list[str] | None:
        """Очистка и приведение к lowercase."""
        cleaned = clean_and_deduplicate_strings(v)
        if cleaned:
            # Приводим к lowercase для регистронезависимого поиска
            cleaned = [s.lower() for s in cleaned]
        return cleaned

    @field_validator("patterns")
    @classmethod
    def validate_patterns(cls, v: list[str] | None) -> list[str] | None:
        return validate_regex_patterns(v, field_name="patterns")

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and len(v) == 0:
            return None
        return v

