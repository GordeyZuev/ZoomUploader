"""Модели базы данных для автоматизации обработки записей."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import relationship

from database.models import Base


class AutomationJobModel(Base):
    """Модель задачи автоматизации для синхронизации и обработки записей по расписанию."""

    __tablename__ = "automation_jobs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    source_id = Column(Integer, ForeignKey("input_sources.id", ondelete="CASCADE"), nullable=False, index=True)
    template_ids = Column(ARRAY(Integer), nullable=False, server_default="{}")

    schedule = Column(JSONB, nullable=False)
    sync_config = Column(JSONB, nullable=False, server_default='{"sync_days": 2, "allow_skipped": false}')
    processing_config = Column(JSONB, nullable=False, server_default='{"auto_process": true, "auto_upload": true, "max_parallel": 3}')

    is_active = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    run_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("UserModel", back_populates="automation_jobs")
    source = relationship("InputSourceModel")

    def __repr__(self):
        return f"<AutomationJob(id={self.id}, user_id={self.user_id}, name='{self.name}', active={self.is_active})>"

