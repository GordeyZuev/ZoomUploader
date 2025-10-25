from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Identity, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from models.recording import PlatformStatus, ProcessingStatus


class Base(DeclarativeBase):
    pass


class RecordingModel(Base):
    """Модель записи Zoom встречи в базе данных"""

    __tablename__ = "recordings"

    # Уникальное ограничение по комбинации meeting_id и start_time
    __table_args__ = (
        UniqueConstraint('meeting_id', 'start_time', name='unique_meeting_start_time'),
    )

    # Первичный ключ - автоинкрементный ID
    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)

    # Основные поля
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)  # в минутах
    share_url: Mapped[str | None] = mapped_column(String(1000))
    auto_delete_date: Mapped[str | None] = mapped_column(String(50))
    meeting_id: Mapped[str] = mapped_column(String(100), nullable=False)
    account: Mapped[str | None] = mapped_column(String(255))  # Email аккаунта Zoom

    # Файлы
    video_file_download_url: Mapped[str | None] = mapped_column(String(1000))
    video_file_size: Mapped[int] = mapped_column(Integer, default=0)

    # Информация о доступе
    password: Mapped[str | None] = mapped_column(String(100))
    recording_play_passcode: Mapped[str | None] = mapped_column(String(500))
    download_access_token: Mapped[str | None] = mapped_column(String(1000))

    # Локальные файлы
    local_video_path: Mapped[str | None] = mapped_column(String(1000))
    processed_video_path: Mapped[str | None] = mapped_column(String(1000))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Маппинг и статусы
    is_mapped: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.INITIALIZED
    )

    # Платформы
    youtube_status: Mapped[str] = mapped_column(
        Enum(PlatformStatus), default=PlatformStatus.NOT_UPLOADED
    )
    youtube_url: Mapped[str | None] = mapped_column(String(1000))
    vk_status: Mapped[str] = mapped_column(
        Enum(PlatformStatus), default=PlatformStatus.NOT_UPLOADED
    )
    vk_url: Mapped[str | None] = mapped_column(String(1000))

    # Метаданные обработки
    processing_notes: Mapped[str | None] = mapped_column(Text)
    processing_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<Recording(id={self.id}, topic='{self.topic}', status={self.status})>"
