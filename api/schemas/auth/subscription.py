"""Pydantic схемы для подписок и тарифных планов."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# ========================================
# SUBSCRIPTION PLANS
# ========================================


class SubscriptionPlanBase(BaseModel):
    """Базовая схема тарифного плана."""

    name: str = Field(..., max_length=50, description="Уникальное имя плана")
    display_name: str = Field(..., max_length=100, description="Отображаемое имя")
    description: str | None = Field(None, description="Описание плана")

    # Included quotas (None = unlimited)
    included_recordings_per_month: int | None = Field(None, ge=0, description="Записей в месяц")
    included_storage_gb: int | None = Field(None, ge=0, description="Хранилище (GB)")
    max_concurrent_tasks: int | None = Field(None, ge=1, description="Одновременных задач")
    max_automation_jobs: int | None = Field(None, ge=0, description="Automation jobs")
    min_automation_interval_hours: int | None = Field(None, ge=1, description="Мин. интервал (часы)")

    # Pricing
    price_monthly: Decimal = Field(Decimal("0.00"), ge=0, description="Цена в месяц")
    price_yearly: Decimal = Field(Decimal("0.00"), ge=0, description="Цена в год")

    # Pay-as-you-go (for future)
    overage_price_per_unit: Decimal | None = Field(None, ge=0, description="Цена за единицу overage")
    overage_unit_type: str | None = Field(None, max_length=50, description="Тип единицы")


class SubscriptionPlanCreate(SubscriptionPlanBase):
    """Схема для создания тарифного плана."""

    is_active: bool = Field(True, description="Активен ли план")
    sort_order: int = Field(0, description="Порядок сортировки")


class SubscriptionPlanUpdate(BaseModel):
    """Схема для обновления тарифного плана."""

    display_name: str | None = Field(None, max_length=100)
    description: str | None = None

    included_recordings_per_month: int | None = Field(None, ge=0)
    included_storage_gb: int | None = Field(None, ge=0)
    max_concurrent_tasks: int | None = Field(None, ge=1)
    max_automation_jobs: int | None = Field(None, ge=0)
    min_automation_interval_hours: int | None = Field(None, ge=1)

    price_monthly: Decimal | None = Field(None, ge=0)
    price_yearly: Decimal | None = Field(None, ge=0)

    overage_price_per_unit: Decimal | None = Field(None, ge=0)
    overage_unit_type: str | None = Field(None, max_length=50)

    is_active: bool | None = None
    sort_order: int | None = None


class SubscriptionPlanInDB(SubscriptionPlanBase):
    """Схема тарифного плана в БД."""

    id: int
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SubscriptionPlanResponse(BaseModel):
    """Схема ответа с тарифным планом."""

    id: int
    name: str
    display_name: str
    description: str | None

    included_recordings_per_month: int | None
    included_storage_gb: int | None
    max_concurrent_tasks: int | None
    max_automation_jobs: int | None
    min_automation_interval_hours: int | None

    price_monthly: Decimal
    price_yearly: Decimal

    is_active: bool
    sort_order: int

    class Config:
        from_attributes = True


# ========================================
# USER SUBSCRIPTIONS
# ========================================


class UserSubscriptionBase(BaseModel):
    """Базовая схема подписки пользователя."""

    plan_id: int = Field(..., description="ID тарифного плана")


class UserSubscriptionCreate(UserSubscriptionBase):
    """Схема для создания подписки."""

    user_id: int = Field(..., description="ID пользователя")

    # Custom quotas (optional overrides)
    custom_max_recordings_per_month: int | None = Field(None, ge=0)
    custom_max_storage_gb: int | None = Field(None, ge=0)
    custom_max_concurrent_tasks: int | None = Field(None, ge=1)
    custom_max_automation_jobs: int | None = Field(None, ge=0)
    custom_min_automation_interval_hours: int | None = Field(None, ge=1)

    # Pay-as-you-go
    pay_as_you_go_enabled: bool = Field(False, description="Включен ли Pay-as-you-go")
    pay_as_you_go_monthly_limit: Decimal | None = Field(None, ge=0, description="Лимит overage в месяц")

    # Period
    starts_at: datetime | None = None
    expires_at: datetime | None = None

    # Audit
    created_by: int | None = None
    notes: str | None = None


class UserSubscriptionUpdate(BaseModel):
    """Схема для обновления подписки."""

    plan_id: int | None = None

    # Custom quotas
    custom_max_recordings_per_month: int | None = Field(None, ge=0)
    custom_max_storage_gb: int | None = Field(None, ge=0)
    custom_max_concurrent_tasks: int | None = Field(None, ge=1)
    custom_max_automation_jobs: int | None = Field(None, ge=0)
    custom_min_automation_interval_hours: int | None = Field(None, ge=1)

    # Pay-as-you-go
    pay_as_you_go_enabled: bool | None = None
    pay_as_you_go_monthly_limit: Decimal | None = Field(None, ge=0)

    # Period
    expires_at: datetime | None = None

    # Audit
    modified_by: int | None = None
    notes: str | None = None


class UserSubscriptionInDB(UserSubscriptionBase):
    """Схема подписки в БД."""

    id: int
    user_id: int

    custom_max_recordings_per_month: int | None
    custom_max_storage_gb: int | None
    custom_max_concurrent_tasks: int | None
    custom_max_automation_jobs: int | None
    custom_min_automation_interval_hours: int | None

    pay_as_you_go_enabled: bool
    pay_as_you_go_monthly_limit: Decimal | None

    starts_at: datetime
    expires_at: datetime | None

    created_by: int | None
    modified_by: int | None
    notes: str | None

    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserSubscriptionResponse(BaseModel):
    """Схема ответа с подпиской пользователя."""

    id: int
    user_id: int
    plan: SubscriptionPlanResponse

    # Custom quotas (if set)
    custom_max_recordings_per_month: int | None
    custom_max_storage_gb: int | None
    custom_max_concurrent_tasks: int | None
    custom_max_automation_jobs: int | None
    custom_min_automation_interval_hours: int | None

    # Effective quotas (with custom overrides applied)
    effective_max_recordings_per_month: int | None
    effective_max_storage_gb: int | None
    effective_max_concurrent_tasks: int | None
    effective_max_automation_jobs: int | None
    effective_min_automation_interval_hours: int | None

    pay_as_you_go_enabled: bool
    pay_as_you_go_monthly_limit: Decimal | None

    starts_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True


# ========================================
# QUOTA USAGE
# ========================================


class QuotaUsageBase(BaseModel):
    """Базовая схема использования квот."""

    user_id: int
    period: int  # YYYYMM


class QuotaUsageCreate(QuotaUsageBase):
    """Схема для создания записи использования."""

    recordings_count: int = 0
    storage_bytes: int = 0
    concurrent_tasks_count: int = 0


class QuotaUsageUpdate(BaseModel):
    """Схема для обновления использования."""

    recordings_count: int | None = Field(None, ge=0)
    storage_bytes: int | None = Field(None, ge=0)
    concurrent_tasks_count: int | None = Field(None, ge=0)
    overage_recordings_count: int | None = Field(None, ge=0)
    overage_cost: Decimal | None = Field(None, ge=0)


class QuotaUsageInDB(QuotaUsageBase):
    """Схема использования в БД."""

    id: int
    recordings_count: int
    storage_bytes: int
    concurrent_tasks_count: int
    overage_recordings_count: int
    overage_cost: Decimal
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class QuotaUsageResponse(BaseModel):
    """Схема ответа с использованием квот."""

    period: int
    recordings_count: int
    storage_gb: float  # Converted from bytes
    concurrent_tasks_count: int
    overage_recordings_count: int
    overage_cost: Decimal

    class Config:
        from_attributes = True


class QuotaStatusResponse(BaseModel):
    """Схема ответа со статусом квот пользователя."""

    # Current subscription
    subscription: UserSubscriptionResponse

    # Current period usage
    current_usage: QuotaUsageResponse | None

    # Quota status
    recordings: dict[str, int | None]  # {"used": 5, "limit": 10, "available": 5}
    storage: dict[str, float | None]  # {"used_gb": 2.5, "limit_gb": 5, "available_gb": 2.5}
    concurrent_tasks: dict[str, int | None]
    automation_jobs: dict[str, int | None]

    # Overage status
    is_overage_enabled: bool
    overage_cost_this_month: Decimal
    overage_limit: Decimal | None

    class Config:
        from_attributes = True
