"""Модели базы данных для аутентификации и multi-tenancy."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    timezone = Column(String(50), default="UTC", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    credentials = relationship("UserCredentialModel", back_populates="user", cascade="all, delete-orphan")
    recordings = relationship("RecordingModel", back_populates="owner", cascade="all, delete-orphan")
    subscription = relationship(
        "UserSubscriptionModel",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="[UserSubscriptionModel.user_id]"
    )
    quota_usage = relationship("QuotaUsageModel", back_populates="user", cascade="all, delete-orphan")
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


class SubscriptionPlanModel(Base):
    """Модель тарифного плана."""

    __tablename__ = "subscription_plans"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(50), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # Included quotas (NULL = unlimited)
    included_recordings_per_month = Column(Integer, nullable=True)
    included_storage_gb = Column(Integer, nullable=True)
    max_concurrent_tasks = Column(Integer, nullable=True)
    max_automation_jobs = Column(Integer, nullable=True)
    min_automation_interval_hours = Column(Integer, nullable=True)

    # Subscription pricing
    price_monthly = Column(Numeric(10, 2), default=0, nullable=False)
    price_yearly = Column(Numeric(10, 2), default=0, nullable=False)

    # Pay-as-you-go pricing (for future)
    overage_price_per_unit = Column(Numeric(10, 4), nullable=True)
    overage_unit_type = Column(String(50), nullable=True)

    # Metadata
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    sort_order = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    subscriptions = relationship("UserSubscriptionModel", back_populates="plan")

    def __repr__(self):
        return f"<SubscriptionPlan(id={self.id}, name='{self.name}', display_name='{self.display_name}')>"


class UserSubscriptionModel(Base):
    """Модель подписки пользователя."""

    __tablename__ = "user_subscriptions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False, index=True)

    # Custom quotas (override plan defaults, NULL = use from plan)
    custom_max_recordings_per_month = Column(Integer, nullable=True)
    custom_max_storage_gb = Column(Integer, nullable=True)
    custom_max_concurrent_tasks = Column(Integer, nullable=True)
    custom_max_automation_jobs = Column(Integer, nullable=True)
    custom_min_automation_interval_hours = Column(Integer, nullable=True)

    # Pay-as-you-go control (for future)
    pay_as_you_go_enabled = Column(Boolean, default=False, nullable=False)
    pay_as_you_go_monthly_limit = Column(Numeric(10, 2), nullable=True)

    # Subscription period
    starts_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    # Audit
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    modified_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("UserModel", back_populates="subscription", foreign_keys=[user_id])
    plan = relationship("SubscriptionPlanModel", back_populates="subscriptions")

    def __repr__(self):
        return f"<UserSubscription(id={self.id}, user_id={self.user_id}, plan_id={self.plan_id})>"


class QuotaUsageModel(Base):
    """Модель использования квот."""

    __tablename__ = "quota_usage"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(Integer, nullable=False, index=True)  # YYYYMM format

    # Usage counters
    recordings_count = Column(Integer, default=0, nullable=False)
    storage_bytes = Column(BigInteger, default=0, nullable=False)
    concurrent_tasks_count = Column(Integer, default=0, nullable=False)

    # Overage counters (for future billing)
    overage_recordings_count = Column(Integer, default=0, nullable=False)
    overage_cost = Column(Numeric(10, 2), default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("UserModel", back_populates="quota_usage")

    def __repr__(self):
        return (
            f"<QuotaUsage(id={self.id}, user_id={self.user_id}, period={self.period}, "
            f"recordings={self.recordings_count})>"
        )


class QuotaChangeHistoryModel(Base):
    """Модель истории изменений квот."""

    __tablename__ = "quota_change_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    changed_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    change_type = Column(String(50), nullable=False, index=True)

    # What changed
    old_plan_id = Column(Integer, ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True)
    new_plan_id = Column(Integer, ForeignKey("subscription_plans.id", ondelete="SET NULL"), nullable=True)
    changes = Column(JSONB, nullable=True)
    notes = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    def __repr__(self):
        return f"<QuotaChangeHistory(id={self.id}, user_id={self.user_id}, type='{self.change_type}')>"


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
