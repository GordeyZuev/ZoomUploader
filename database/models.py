from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from models.recording import ProcessingStatus, SourceType, TargetStatus, TargetType


class Base(DeclarativeBase):
    pass


class RecordingModel(Base):
    """Универсальная запись."""

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)

    # Основные поля
    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)  # в минутах
    status: Mapped[str] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.INITIALIZED
    )
    is_mapped: Mapped[bool] = mapped_column(Boolean, default=False)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Пути (относительно media_dir)
    local_video_path: Mapped[str | None] = mapped_column(String(1000))
    processed_video_path: Mapped[str | None] = mapped_column(String(1000))
    processed_audio_dir: Mapped[str | None] = mapped_column(String(1000))
    transcription_dir: Mapped[str | None] = mapped_column(String(1000))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Дополнительные поля
    video_file_size: Mapped[int | None] = mapped_column(Integer)
    transcription_info: Mapped[Any | None] = mapped_column(JSONB)
    topic_timestamps: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    main_topics: Mapped[Any | None] = mapped_column(JSONB, nullable=True)

    # Временные метки
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    source: Mapped["SourceMetadataModel"] = relationship(
        "SourceMetadataModel",
        back_populates="recording",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="SourceMetadataModel.recording_id",
        primaryjoin="RecordingModel.id==SourceMetadataModel.recording_id",
    )
    outputs: Mapped[list["OutputTargetModel"]] = relationship(
        "OutputTargetModel", back_populates="recording", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Recording(id={self.id}, display_name='{self.display_name}', status={self.status})>"


class SourceMetadataModel(Base):
    """Метаданные источника записи."""

    __tablename__ = "source_metadata"

    __table_args__ = (
        UniqueConstraint("source_type", "source_key", "recording_id", name="unique_source_per_recording"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    recording_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recordings.id", ondelete="CASCADE"), unique=True
    )
    source_type: Mapped[str] = mapped_column(Enum(SourceType))
    source_key: Mapped[str] = mapped_column(String(1000))
    meta: Mapped[Any | None] = mapped_column("metadata", JSONB)

    recording: Mapped[RecordingModel] = relationship(
        "RecordingModel",
        back_populates="source",
        foreign_keys=[recording_id],
        primaryjoin="SourceMetadataModel.recording_id==RecordingModel.id",
    )


class OutputTargetModel(Base):
    """Целевая платформа/хранилище для выгрузки."""

    __tablename__ = "output_targets"

    __table_args__ = (
        UniqueConstraint("recording_id", "target_type", name="unique_target_per_recording"),
    )

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    recording_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recordings.id", ondelete="CASCADE")
    )
    target_type: Mapped[str] = mapped_column(Enum(TargetType))
    status: Mapped[str] = mapped_column(Enum(TargetStatus), default=TargetStatus.NOT_UPLOADED)
    target_meta: Mapped[Any | None] = mapped_column(JSONB)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    recording: Mapped[RecordingModel] = relationship("RecordingModel", back_populates="outputs")
