from datetime import datetime
from typing import TYPE_CHECKING, Any

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

from models.recording import (
    ProcessingStageStatus,
    ProcessingStageType,
    ProcessingStatus,
    SourceType,
    TargetStatus,
    TargetType,
)

if TYPE_CHECKING:
    from database.auth_models import UserModel
    from database.template_models import InputSourceModel, OutputPresetModel


class Base(DeclarativeBase):
    pass


class RecordingModel(Base):
    """Универсальная запись."""

    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    input_source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("input_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )

    display_name: Mapped[str] = mapped_column(String(500), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Enum(ProcessingStatus), default=ProcessingStatus.INITIALIZED)
    is_mapped: Mapped[bool] = mapped_column(Boolean, default=False)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_video_path: Mapped[str | None] = mapped_column(String(1000))
    processed_video_path: Mapped[str | None] = mapped_column(String(1000))
    processed_audio_dir: Mapped[str | None] = mapped_column(String(1000))
    transcription_dir: Mapped[str | None] = mapped_column(String(1000))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    video_file_size: Mapped[int | None] = mapped_column(Integer)
    transcription_info: Mapped[Any | None] = mapped_column(JSONB)
    topic_timestamps: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    main_topics: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    processing_preferences: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_reason: Mapped[str | None] = mapped_column(String(1000))
    failed_at_stage: Mapped[str | None] = mapped_column(String(50))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    owner: Mapped["UserModel"] = relationship("UserModel", back_populates="recordings", lazy="selectin")
    input_source: Mapped["InputSourceModel"] = relationship(
        "InputSourceModel",
        foreign_keys=[input_source_id],
        lazy="selectin",
    )
    source: Mapped["SourceMetadataModel"] = relationship(
        "SourceMetadataModel",
        back_populates="recording",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="SourceMetadataModel.recording_id",
        primaryjoin="RecordingModel.id==SourceMetadataModel.recording_id",
        lazy="selectin",
    )
    outputs: Mapped[list["OutputTargetModel"]] = relationship(
        "OutputTargetModel",
        back_populates="recording",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    processing_stages: Mapped[list["ProcessingStageModel"]] = relationship(
        "ProcessingStageModel",
        back_populates="recording",
        cascade="all, delete-orphan",
        lazy="selectin",
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
    recording_id: Mapped[int] = mapped_column(Integer, ForeignKey("recordings.id", ondelete="CASCADE"), unique=True)
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    input_source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("input_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_type: Mapped[str] = mapped_column(Enum(SourceType))
    source_key: Mapped[str] = mapped_column(String(1000))
    meta: Mapped[Any | None] = mapped_column("metadata", JSONB)

    recording: Mapped[RecordingModel] = relationship(
        "RecordingModel",
        back_populates="source",
        foreign_keys=[recording_id],
        primaryjoin="SourceMetadataModel.recording_id==RecordingModel.id",
        lazy="selectin",
    )
    input_source: Mapped["InputSourceModel"] = relationship(
        "InputSourceModel",
        foreign_keys=[input_source_id],
        lazy="selectin",
    )


class OutputTargetModel(Base):
    """Целевая платформа/хранилище для выгрузки."""

    __tablename__ = "output_targets"

    __table_args__ = (UniqueConstraint("recording_id", "target_type", name="unique_target_per_recording"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, ForeignKey("recordings.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    preset_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("output_presets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_type: Mapped[str] = mapped_column(Enum(TargetType))
    status: Mapped[str] = mapped_column(Enum(TargetStatus), default=TargetStatus.NOT_UPLOADED)
    target_meta: Mapped[Any | None] = mapped_column(JSONB)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    recording: Mapped[RecordingModel] = relationship("RecordingModel", back_populates="outputs", lazy="selectin")
    preset: Mapped["OutputPresetModel"] = relationship(
        "OutputPresetModel",
        foreign_keys=[preset_id],
        lazy="selectin",
    )


class ProcessingStageModel(Base):
    """Этап обработки записи (FSM модель)."""

    __tablename__ = "processing_stages"

    __table_args__ = (UniqueConstraint("recording_id", "stage_type", name="unique_stage_per_recording"),)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    recording_id: Mapped[int] = mapped_column(Integer, ForeignKey("recordings.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage_type: Mapped[str] = mapped_column(Enum(ProcessingStageType))
    status: Mapped[str] = mapped_column(Enum(ProcessingStageStatus), default=ProcessingStageStatus.PENDING)
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_reason: Mapped[str | None] = mapped_column(String(1000))
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    stage_meta: Mapped[Any | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    recording: Mapped["RecordingModel"] = relationship(
        "RecordingModel", back_populates="processing_stages", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<ProcessingStage(id={self.id}, recording_id={self.recording_id}, "
            f"stage_type={self.stage_type}, status={self.status})>"
        )
