"""Video processing configuration"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import settings


class ProcessingConfig(BaseSettings):
    """Video processing configuration"""

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # Main settings
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

    # Video quality
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

    # Audio trimming
    audio_detection: bool = Field(
        default=True,
        description="Включить детекцию звука для автоматической обрезки",
    )
    silence_threshold: float = Field(
        default_factory=lambda: settings.processing.silence_threshold,
        le=0.0,
        description="Silence threshold in dB (must be negative)",
    )
    min_silence_duration: float = Field(
        default_factory=lambda: settings.processing.min_silence_duration,
        gt=0.0,
        description="Minimum silence duration in seconds",
    )
    padding_before: float = Field(
        default_factory=lambda: settings.processing.padding_before,
        ge=0.0,
        description="Padding before sound in seconds",
    )
    padding_after: float = Field(
        default_factory=lambda: settings.processing.padding_after,
        ge=0.0,
        description="Padding after sound in seconds",
    )

    # Trimming (for manual settings)
    trim_start: float | None = Field(
        default=None,
        ge=0.0,
        description="Trim start in seconds",
    )
    trim_end: float | None = Field(
        default=None,
        ge=0.0,
        description="Trim end in seconds",
    )
    max_duration: int | None = Field(
        default=None,
        gt=0,
        description="Maximum duration in seconds",
    )

    # Сегментация
    segment_duration: int = Field(
        default=30,
        gt=0,
        description="Segment duration in seconds",
    )
    overlap_duration: int = Field(
        default=1,
        ge=0,
        description="Overlap between segments in seconds",
    )

    # Папки
    input_dir: str = Field(
        default_factory=lambda: settings.processing.input_dir,
        description="Input directory",
    )
    output_dir: str = Field(
        default_factory=lambda: settings.processing.output_dir,
        description="Output directory",
    )
    temp_dir: str = Field(
        default_factory=lambda: settings.processing.temp_dir,
        description="Temporary directory",
    )

    # Additional options
    remove_intro: bool = Field(
        default_factory=lambda: settings.processing.remove_intro,
        description="Remove intro",
    )
    remove_outro: bool = Field(
        default_factory=lambda: settings.processing.remove_outro,
        description="Remove outro",
    )
    intro_duration: int = Field(
        default_factory=lambda: int(settings.processing.intro_duration),
        ge=0,
        description="Intro duration in seconds",
    )
    outro_duration: int = Field(
        default_factory=lambda: int(settings.processing.outro_duration),
        ge=0,
        description="Outro duration in seconds",
    )

    # Logging
    keep_temp_files: bool = Field(
        default_factory=lambda: settings.processing.keep_temp_files,
        description="Keep temporary files",
    )

    @model_validator(mode="after")
    def validate_config(self) -> ProcessingConfig:
        """Validate field dependencies."""
        # Check overlap_duration < segment_duration
        if self.overlap_duration >= self.segment_duration:
            raise ValueError(
                f"overlap_duration ({self.overlap_duration}) should be less than "
                f"segment_duration ({self.segment_duration})"
            )

        # Check trim_end > trim_start
        if self.trim_start is not None and self.trim_end is not None:
            if self.trim_end <= self.trim_start:
                raise ValueError(f"trim_end ({self.trim_end}) should be greater than trim_start ({self.trim_start})")

        return self
