"""Конфигурация обработки видео с валидацией через Pydantic"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import settings


class ProcessingConfig(BaseSettings):
    """
    Конфигурация обработки видео.

    Использует настройки из config.settings, но может быть переопределена.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # Основные настройки
    output_format: str = Field(
        default="mp4",
        description="Формат выходного видео",
    )
    video_codec: str = Field(
        default_factory=lambda: settings.processing.video_codec,
        description="Видео кодек",
    )
    audio_codec: str = Field(
        default_factory=lambda: settings.processing.audio_codec,
        description="Аудио кодек",
    )

    # Качество видео
    video_bitrate: str = Field(
        default_factory=lambda: settings.processing.video_bitrate,
        description="Битрейт видео",
    )
    audio_bitrate: str = Field(
        default_factory=lambda: settings.processing.audio_bitrate,
        description="Битрейт аудио",
    )
    resolution: str = Field(
        default_factory=lambda: settings.processing.resolution,
        description="Разрешение видео",
    )
    fps: int = Field(
        default_factory=lambda: settings.processing.fps,
        ge=0,
        description="FPS (0 = не изменять)",
    )

    # Обрезка по звуку
    audio_detection: bool = Field(
        default=True,
        description="Включить детекцию звука для автоматической обрезки",
    )
    silence_threshold: float = Field(
        default_factory=lambda: settings.processing.silence_threshold,
        le=0.0,
        description="Порог тишины в дБ (должен быть отрицательным)",
    )
    min_silence_duration: float = Field(
        default_factory=lambda: settings.processing.min_silence_duration,
        gt=0.0,
        description="Минимальная длительность тишины в секундах",
    )
    padding_before: float = Field(
        default_factory=lambda: settings.processing.padding_before,
        ge=0.0,
        description="Отступ до звука в секундах",
    )
    padding_after: float = Field(
        default_factory=lambda: settings.processing.padding_after,
        ge=0.0,
        description="Отступ после звука в секундах",
    )

    # Обрезка (для ручной настройки)
    trim_start: float | None = Field(
        default=None,
        ge=0.0,
        description="Начало обрезки в секундах",
    )
    trim_end: float | None = Field(
        default=None,
        ge=0.0,
        description="Конец обрезки в секундах",
    )
    max_duration: int | None = Field(
        default=None,
        gt=0,
        description="Максимальная длительность в секундах",
    )

    # Сегментация
    segment_duration: int = Field(
        default=30,
        gt=0,
        description="Длительность сегмента в секундах",
    )
    overlap_duration: int = Field(
        default=1,
        ge=0,
        description="Перекрытие между сегментами в секундах",
    )

    # Папки
    input_dir: str = Field(
        default_factory=lambda: settings.processing.input_dir,
        description="Директория входящих видео",
    )
    output_dir: str = Field(
        default_factory=lambda: settings.processing.output_dir,
        description="Директория обработанных видео",
    )
    temp_dir: str = Field(
        default_factory=lambda: settings.processing.temp_dir,
        description="Временная директория",
    )

    # Дополнительные опции
    remove_intro: bool = Field(
        default_factory=lambda: settings.processing.remove_intro,
        description="Удалять вступление",
    )
    remove_outro: bool = Field(
        default_factory=lambda: settings.processing.remove_outro,
        description="Удалять заключение",
    )
    intro_duration: int = Field(
        default_factory=lambda: int(settings.processing.intro_duration),
        ge=0,
        description="Длительность вступления в секундах",
    )
    outro_duration: int = Field(
        default_factory=lambda: int(settings.processing.outro_duration),
        ge=0,
        description="Длительность заключения в секундах",
    )

    # Логирование
    keep_temp_files: bool = Field(
        default_factory=lambda: settings.processing.keep_temp_files,
        description="Сохранять временные файлы",
    )

    @model_validator(mode="after")
    def validate_config(self) -> ProcessingConfig:
        """Валидация зависимостей между полями."""
        # Проверка overlap_duration < segment_duration
        if self.overlap_duration >= self.segment_duration:
            raise ValueError(
                f"overlap_duration ({self.overlap_duration}) должен быть меньше "
                f"segment_duration ({self.segment_duration})"
            )

        # Проверка trim_end > trim_start
        if self.trim_start is not None and self.trim_end is not None:
            if self.trim_end <= self.trim_start:
                raise ValueError(
                    f"trim_end ({self.trim_end}) должен быть больше trim_start ({self.trim_start})"
                )

        return self
