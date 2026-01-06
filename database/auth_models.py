"""Модели базы данных для аутентификации и multi-tenancy."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database.models import Base


class UserModel(Base):
    """Модель пользователя для multi-tenancy."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    role = Column(String(50), default="user", nullable=False)
    can_transcribe = Column(Boolean, default=True, nullable=False)
    can_process_video = Column(Boolean, default=True, nullable=False)
    can_upload = Column(Boolean, default=True, nullable=False)
    can_create_templates = Column(Boolean, default=True, nullable=False)
    can_delete_recordings = Column(Boolean, default=True, nullable=False)
    can_update_uploaded_videos = Column(Boolean, default=True, nullable=False)
    can_manage_credentials = Column(Boolean, default=True, nullable=False)
    can_export_data = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    credentials = relationship("UserCredentialModel", back_populates="user", cascade="all, delete-orphan")
    recordings = relationship("RecordingModel", back_populates="owner", cascade="all, delete-orphan")
    quotas = relationship("UserQuotaModel", back_populates="user", uselist=False, cascade="all, delete-orphan")
    config = relationship("UserConfigModel", back_populates="user", uselist=False, cascade="all, delete-orphan")
    automation_jobs = relationship("AutomationJobModel", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', role={self.role}, active={self.is_active})>"


class UserCredentialModel(Base):
    """Модель для хранения учетных данных пользователя к внешним сервисам."""

    __tablename__ = "user_credentials"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), nullable=False)
    account_name = Column(String(255), nullable=True)
    encrypted_data = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    user = relationship("UserModel", back_populates="credentials")

    def __repr__(self):
        account_str = f", account='{self.account_name}'" if self.account_name else ""
        return f"<UserCredential(id={self.id}, user_id={self.user_id}, platform='{self.platform}'{account_str})>"


class UserQuotaModel(Base):
    """Модель для хранения квот пользователя."""

    __tablename__ = "user_quotas"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    max_recordings_per_month = Column(Integer, default=100, nullable=False)
    max_storage_gb = Column(Integer, default=50, nullable=False)
    max_concurrent_tasks = Column(Integer, default=3, nullable=False)
    max_automation_jobs = Column(Integer, default=5, nullable=False)
    min_automation_interval_hours = Column(Integer, default=1, nullable=False)
    current_recordings_count = Column(Integer, default=0, nullable=False)
    current_storage_gb = Column(Integer, default=0, nullable=False)
    current_tasks_count = Column(Integer, default=0, nullable=False)
    quota_reset_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    user = relationship("UserModel", back_populates="quotas")

    def __repr__(self):
        return (
            f"<UserQuota(id={self.id}, user_id={self.user_id}, "
            f"recordings={self.current_recordings_count}/{self.max_recordings_per_month})>"
        )


class RefreshTokenModel(Base):
    """Модель для хранения refresh токенов."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token = Column(String(500), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked={self.is_revoked})>"
