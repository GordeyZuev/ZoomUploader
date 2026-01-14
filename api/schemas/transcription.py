"""Transcription and topic processing schemas"""

from pydantic import BaseModel, Field

# ============================================================================
# Request Models
# ============================================================================


class ExtractTopicsRequest(BaseModel):
    """Request для извлечения тем."""

    model: str = Field(
        default="deepseek",
        description="Модель для извлечения тем: 'deepseek' или 'fireworks_deepseek'",
    )
    granularity: str = Field(
        default="long",
        description="Режим извлечения: 'short' (крупные темы) или 'long' (детальные темы)",
    )
    version_id: str | None = Field(
        default=None,
        description="ID версии (если не указан, генерируется автоматически)",
    )


class GenerateSubtitlesRequest(BaseModel):
    """Request для генерации субтитров."""

    formats: list[str] = Field(
        default=["srt", "vtt"],
        description="Список форматов субтитров: 'srt', 'vtt'",
    )


class BatchTranscribeRequest(BaseModel):
    """Request для батчевой транскрибации."""

    recording_ids: list[int] = Field(..., description="Список ID записей для транскрибации")
    granularity: str = Field(
        default="long",
        description="Режим извлечения тем: 'short' или 'long'",
    )


# ============================================================================
# Response Models
# ============================================================================


class TopicTimestamp(BaseModel):
    """Топик с временными метками."""

    topic: str
    start: float
    end: float
    type: str | None = None  # "pause" для пауз


class TopicVersion(BaseModel):
    """Версия извлечения топиков."""

    id: str
    model: str
    granularity: str
    created_at: str
    is_active: bool
    main_topics: list[str]
    topic_timestamps: list[TopicTimestamp]
    pauses: list[dict] | None = None


class TranscriptionStats(BaseModel):
    """Статистика транскрибации."""

    words_count: int
    segments_count: int
    total_duration: float


class TranscriptionData(BaseModel):
    """Данные о транскрибации."""

    exists: bool
    created_at: str | None = None
    language: str | None = None
    model: str | None = None
    stats: TranscriptionStats | None = None
    files: dict[str, str] | None = None


class TopicsData(BaseModel):
    """Данные о топиках."""

    exists: bool
    active_version: str | None = None
    versions: list[TopicVersion] | None = None


class VideoFileInfo(BaseModel):
    """Информация о видео файле."""

    path: str | None = None
    size_mb: float | None = None
    exists: bool = False


class AudioFileInfo(BaseModel):
    """Информация об аудио файле."""

    path: str | None = None
    size_mb: float | None = None
    exists: bool = False


class SubtitleFileInfo(BaseModel):
    """Информация о файле субтитров."""

    path: str | None = None
    exists: bool = False
    size_kb: float | None = None


class ThumbnailInfo(BaseModel):
    """Информация о thumbnail."""

    path: str | None = None
    exists: bool = False
    type: str | None = None  # "template" или "user"


class RecordingDetailsResponse(BaseModel):
    """Детальная информация о записи."""

    id: int
    display_name: str
    status: str
    start_time: str
    duration: int | None = None

    # Видео файлы
    videos: dict[str, VideoFileInfo] | None = None

    # Аудио файлы
    audio: AudioFileInfo | None = None

    # Транскрибация
    transcription: TranscriptionData | None = None

    # Топики (все версии)
    topics: TopicsData | None = None

    # Субтитры
    subtitles: dict[str, SubtitleFileInfo] | None = None

    # Thumbnail
    thumbnail: ThumbnailInfo | None = None

    # Этапы обработки
    processing_stages: list[dict] | None = None

    # Загрузка на платформы
    uploads: dict[str, dict] | None = None


class ExtractTopicsResponse(BaseModel):
    """Response для извлечения тем."""

    success: bool
    task_id: str
    recording_id: int
    status: str
    message: str
    check_status_url: str


class GenerateSubtitlesResponse(BaseModel):
    """Response для генерации субтитров."""

    success: bool
    task_id: str
    recording_id: int
    status: str
    message: str
    check_status_url: str


class BatchTranscribeTaskInfo(BaseModel):
    """Информация о задаче батчевой транскрибации."""

    recording_id: int
    status: str
    task_id: str | None = None
    error: str | None = None
    check_status_url: str | None = None


class BatchTranscribeResponse(BaseModel):
    """Response для батчевой транскрибации."""

    total: int
    queued: int
    errors: int
    tasks: list[BatchTranscribeTaskInfo]

