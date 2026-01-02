"""Модели для шаблонов, конфигураций, источников и пресетов."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from database.models import Base


class BaseConfigModel(Base):
    """Базовая конфигурация (глобальная или пользовательская)."""

    __tablename__ = "base_configs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    config_type = Column(String(50), nullable=True, index=True)
    config_data = Column(JSONB, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        scope = "global" if self.user_id is None else f"user_{self.user_id}"
        return f"<BaseConfig(id={self.id}, name='{self.name}', scope={scope})>"


class InputSourceModel(Base):
    """Источник данных для синхронизации записей."""

    __tablename__ = "input_sources"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Основные поля
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String(50), nullable=False)
    credential_id = Column(Integer, ForeignKey("user_credentials.id", ondelete="SET NULL"), nullable=True)
    config = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_sync_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    credential = relationship("UserCredentialModel", foreign_keys=[credential_id])

    def __repr__(self):
        return f"<InputSource(id={self.id}, name='{self.name}', type={self.source_type}, user_id={self.user_id})>"


class OutputPresetModel(Base):
    """Пресет для выгрузки на платформу."""

    __tablename__ = "output_presets"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    platform = Column(String(50), nullable=False)
    credential_id = Column(Integer, ForeignKey("user_credentials.id", ondelete="CASCADE"), nullable=False)
    preset_metadata = Column(JSONB, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    credential = relationship("UserCredentialModel", foreign_keys=[credential_id])

    def __repr__(self):
        return f"<OutputPreset(id={self.id}, name='{self.name}', platform={self.platform}, user_id={self.user_id})>"


class RecordingTemplateModel(Base):
    """Шаблон для автоматической обработки записей."""

    __tablename__ = "recording_templates"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    matching_rules = Column(JSONB, nullable=True)
    priority = Column(Integer, default=0, nullable=False)
    processing_config = Column(JSONB, nullable=True)
    metadata_config = Column(JSONB, nullable=True)
    output_config = Column(JSONB, nullable=True)
    is_draft = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    used_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        draft_status = " (draft)" if self.is_draft else ""
        return f"<RecordingTemplate(id={self.id}, name='{self.name}', user_id={self.user_id}{draft_status})>"

