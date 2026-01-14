"""Admin statistics schemas"""

from decimal import Decimal

from pydantic import BaseModel, Field


class AdminOverviewStats(BaseModel):
    """Общая статистика платформы."""

    total_users: int = Field(..., description="Всего пользователей")
    active_users: int = Field(..., description="Активных пользователей")
    total_recordings: int = Field(..., description="Всего записей")
    total_storage_gb: float = Field(..., description="Всего использовано хранилища (GB)")
    total_plans: int = Field(..., description="Всего тарифных планов")
    users_by_plan: dict[str, int] = Field(
        ..., description="Распределение пользователей по планам"
    )


class UserQuotaDetails(BaseModel):
    """Детальная информация о квотах пользователя."""

    user_id: int
    email: str
    plan_name: str
    recordings_used: int
    recordings_limit: int | None
    storage_used_gb: float
    storage_limit_gb: int | None
    is_exceeding: bool = Field(..., description="Превышены ли квоты")
    overage_enabled: bool
    overage_cost: Decimal = Field(default=Decimal("0"))


class AdminUserStats(BaseModel):
    """Статистика по пользователям с фильтрами."""

    total_count: int
    users: list[UserQuotaDetails]
    page: int = 1
    page_size: int = 50


class PlanUsageStats(BaseModel):
    """Статистика использования по плану."""

    plan_name: str
    total_users: int
    total_recordings: int
    total_storage_gb: float
    avg_recordings_per_user: float
    avg_storage_per_user_gb: float


class AdminQuotaStats(BaseModel):
    """Статистика использования квот."""

    period: int = Field(..., description="Период (YYYYMM)")
    total_recordings: int
    total_storage_gb: float
    total_overage_cost: Decimal
    plans: list[PlanUsageStats]

