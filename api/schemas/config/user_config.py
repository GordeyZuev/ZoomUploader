from datetime import datetime

from pydantic import BaseModel, Field


class ProcessingConfig(BaseModel):
    enable_processing: bool = True
    audio_detection: bool = True
    silence_threshold: float = -40.0
    min_silence_duration: float = 2.0
    padding_before: float = 5.0
    padding_after: float = 5.0


class TranscriptionConfig(BaseModel):
    enable_transcription: bool = True
    provider: str = "fireworks"
    language: str = "ru"
    prompt: str = ""
    temperature: float = 0.0
    enable_topics: bool = True
    granularity: str = "long"  # "short" или "long" - уровень детализации извлечения тем
    enable_subtitles: bool = True
    enable_translation: bool = False
    translation_language: str = "en"


class DownloadConfig(BaseModel):
    auto_download: bool = False
    max_file_size_mb: int = 5000
    quality: str = "high"
    retry_attempts: int = 3
    retry_delay: int = 5


class UploadConfig(BaseModel):
    auto_upload: bool = False
    upload_captions: bool = True
    default_platforms: list[str] = Field(default_factory=list)
    default_preset_ids: dict[str, int] = Field(default_factory=dict)


class TopicsDisplayConfig(BaseModel):
    enabled: bool = True
    max_count: int = 10
    min_length: int = 5
    max_length: int = 100
    display_location: str = "description"
    format: str = "numbered_list"
    separator: str = "\n"
    prefix: str = "Темы:"
    include_timestamps: bool = False


class MetadataConfig(BaseModel):
    title_template: str = "{display_name} | {topic} ({date})"
    description_template: str = "Запись от {date}"
    date_format: str = "DD.MM.YYYY"
    tags: list[str] = Field(default_factory=list)
    thumbnail_path: str | None = None
    category: str | None = None
    topics_display: TopicsDisplayConfig = Field(default_factory=TopicsDisplayConfig)


class PlatformSettings(BaseModel):
    enabled: bool = False
    default_privacy: str = "unlisted"
    default_language: str = "ru"
    privacy_comment: str | None = None
    no_comments: bool | None = None
    repeat: bool | None = None


class UserConfigData(BaseModel):
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)
    download: DownloadConfig = Field(default_factory=DownloadConfig)
    upload: UploadConfig = Field(default_factory=UploadConfig)
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)
    platforms: dict[str, PlatformSettings] = Field(default_factory=dict)


class UserConfigResponse(BaseModel):
    id: int
    user_id: int
    config_data: UserConfigData
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserConfigUpdate(BaseModel):
    processing: ProcessingConfig | None = None
    transcription: TranscriptionConfig | None = None
    download: DownloadConfig | None = None
    upload: UploadConfig | None = None
    metadata: MetadataConfig | None = None
    platforms: dict[str, PlatformSettings] | None = None
