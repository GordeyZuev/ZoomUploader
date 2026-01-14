"""Platform management admin endpoints"""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.admin import get_current_admin
from api.dependencies import get_db_session
from api.schemas.admin import (
    AdminOverviewStats,
    AdminQuotaStats,
    AdminUserStats,
    PlanUsageStats,
    UserQuotaDetails,
)
from api.schemas.auth import UserInDB
from database.auth_models import (
    QuotaUsageModel,
    SubscriptionPlanModel,
    UserModel,
    UserSubscriptionModel,
)
from logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


@router.get("/stats/overview", response_model=AdminOverviewStats)
async def get_overview_stats(
    session: AsyncSession = Depends(get_db_session),
    _admin: UserInDB = Depends(get_current_admin),
):
    """
    Получить общую статистику платформы.

    Требует роль: admin

    Returns:
        AdminOverviewStats: Общая статистика
    """
    # Total users
    result = await session.execute(select(func.count(UserModel.id)))
    total_users = result.scalar() or 0

    # Active users
    result = await session.execute(select(func.count(UserModel.id)).where(UserModel.is_active == True))  # noqa: E712
    active_users = result.scalar() or 0

    # Total recordings (need to import RecordingModel)
    from database.models import RecordingModel

    result = await session.execute(select(func.count(RecordingModel.id)))
    total_recordings = result.scalar() or 0

    # Total storage from current period
    current_period = int(datetime.now().strftime("%Y%m"))
    result = await session.execute(
        select(func.sum(QuotaUsageModel.storage_bytes)).where(QuotaUsageModel.period == current_period)
    )
    total_storage_bytes = result.scalar() or 0
    total_storage_gb = total_storage_bytes / (1024**3)

    # Total plans
    result = await session.execute(
        select(func.count(SubscriptionPlanModel.id)).where(SubscriptionPlanModel.is_active == True)  # noqa: E712
    )
    total_plans = result.scalar() or 0

    # Users by plan
    result = await session.execute(
        select(SubscriptionPlanModel.name, func.count(UserSubscriptionModel.user_id))
        .join(UserSubscriptionModel, SubscriptionPlanModel.id == UserSubscriptionModel.plan_id)
        .group_by(SubscriptionPlanModel.name)
    )
    users_by_plan = {row[0]: row[1] for row in result.all()}

    return AdminOverviewStats(
        total_users=total_users,
        active_users=active_users,
        total_recordings=total_recordings,
        total_storage_gb=round(total_storage_gb, 2),
        total_plans=total_plans,
        users_by_plan=users_by_plan,
    )


@router.get("/stats/users", response_model=AdminUserStats)
async def get_user_stats(
    session: AsyncSession = Depends(get_db_session),
    _admin: UserInDB = Depends(get_current_admin),
    page: int = Query(1, ge=1, description="Номер страницы"),
    page_size: int = Query(50, ge=1, le=100, description="Размер страницы"),
    exceeded_only: bool = Query(False, description="Только пользователи с превышением квот"),
    plan_name: str | None = Query(None, description="Фильтр по имени плана"),
):
    """
    Получить детальную статистику по пользователям.

    Требует роль: admin

    Args:
        page: Номер страницы (начиная с 1)
        page_size: Количество пользователей на странице (макс 100)
        exceeded_only: Показать только пользователей с превышением квот
        plan_name: Фильтр по имени плана (free, plus, pro, enterprise)

    Returns:
        AdminUserStats: Статистика по пользователям с пагинацией
    """
    current_period = int(datetime.now().strftime("%Y%m"))

    # Build query
    query = (
        select(
            UserModel.id,
            UserModel.email,
            SubscriptionPlanModel.name.label("plan_name"),
            SubscriptionPlanModel.included_recordings_per_month,
            SubscriptionPlanModel.included_storage_gb,
            UserSubscriptionModel.custom_max_recordings_per_month,
            UserSubscriptionModel.custom_max_storage_gb,
            UserSubscriptionModel.pay_as_you_go_enabled,
            QuotaUsageModel.recordings_count,
            QuotaUsageModel.storage_bytes,
            QuotaUsageModel.overage_cost,
        )
        .join(UserSubscriptionModel, UserModel.id == UserSubscriptionModel.user_id)
        .join(SubscriptionPlanModel, UserSubscriptionModel.plan_id == SubscriptionPlanModel.id)
        .outerjoin(
            QuotaUsageModel,
            (QuotaUsageModel.user_id == UserModel.id) & (QuotaUsageModel.period == current_period),
        )
    )

    # Apply filters
    if plan_name:
        query = query.where(SubscriptionPlanModel.name == plan_name)

    # Execute query for total count
    count_result = await session.execute(select(func.count()).select_from(query.subquery()))
    total_count = count_result.scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await session.execute(query)
    rows = result.all()

    # Build user details
    users = []
    for row in rows:
        user_id = row[0]
        email = row[1]
        plan_name_val = row[2]
        plan_recordings_limit = row[3]
        plan_storage_limit = row[4]
        custom_recordings_limit = row[5]
        custom_storage_limit = row[6]
        overage_enabled = row[7]
        recordings_used = row[8] or 0
        storage_bytes_used = row[9] or 0
        overage_cost = row[10] or Decimal("0")

        # Effective limits (custom overrides plan)
        recordings_limit = custom_recordings_limit or plan_recordings_limit
        storage_limit = custom_storage_limit or plan_storage_limit

        # Check if exceeding
        is_exceeding = False
        if recordings_limit is not None and recordings_used > recordings_limit:
            is_exceeding = True
        if storage_limit is not None and (storage_bytes_used / (1024**3)) > storage_limit:
            is_exceeding = True

        # Apply exceeded_only filter
        if exceeded_only and not is_exceeding:
            continue

        users.append(
            UserQuotaDetails(
                user_id=user_id,
                email=email,
                plan_name=plan_name_val,
                recordings_used=recordings_used,
                recordings_limit=recordings_limit,
                storage_used_gb=round(storage_bytes_used / (1024**3), 2),
                storage_limit_gb=storage_limit,
                is_exceeding=is_exceeding,
                overage_enabled=overage_enabled,
                overage_cost=overage_cost,
            )
        )

    return AdminUserStats(total_count=total_count, users=users, page=page, page_size=page_size)


@router.get("/stats/quotas", response_model=AdminQuotaStats)
async def get_quota_stats(
    session: AsyncSession = Depends(get_db_session),
    _admin: UserInDB = Depends(get_current_admin),
    period: int | None = Query(None, description="Период (YYYYMM), по умолчанию текущий"),
):
    """
    Получить статистику использования квот по планам.

    Требует роль: admin

    Args:
        period: Период (YYYYMM), если не указан - текущий

    Returns:
        AdminQuotaStats: Статистика использования квот
    """
    if not period:
        period = int(datetime.now().strftime("%Y%m"))

    # Total usage for period
    result = await session.execute(
        select(
            func.sum(QuotaUsageModel.recordings_count),
            func.sum(QuotaUsageModel.storage_bytes),
            func.sum(QuotaUsageModel.overage_cost),
        ).where(QuotaUsageModel.period == period)
    )
    row = result.first()
    total_recordings = row[0] or 0
    total_storage_bytes = row[1] or 0
    total_overage_cost = row[2] or Decimal("0")

    # Usage by plan
    result = await session.execute(
        select(
            SubscriptionPlanModel.name,
            func.count(UserSubscriptionModel.user_id).label("total_users"),
            func.sum(QuotaUsageModel.recordings_count).label("total_recordings"),
            func.sum(QuotaUsageModel.storage_bytes).label("total_storage"),
        )
        .join(UserSubscriptionModel, SubscriptionPlanModel.id == UserSubscriptionModel.plan_id)
        .outerjoin(
            QuotaUsageModel,
            (QuotaUsageModel.user_id == UserSubscriptionModel.user_id)
            & (QuotaUsageModel.period == period),
        )
        .group_by(SubscriptionPlanModel.name)
    )

    plans = []
    for row in result.all():
        plan_name = row[0]
        total_users = row[1]
        plan_recordings = row[2] or 0
        plan_storage_bytes = row[3] or 0

        avg_recordings = plan_recordings / total_users if total_users > 0 else 0
        avg_storage_gb = (plan_storage_bytes / (1024**3)) / total_users if total_users > 0 else 0

        plans.append(
            PlanUsageStats(
                plan_name=plan_name,
                total_users=total_users,
                total_recordings=plan_recordings,
                total_storage_gb=round(plan_storage_bytes / (1024**3), 2),
                avg_recordings_per_user=round(avg_recordings, 2),
                avg_storage_per_user_gb=round(avg_storage_gb, 2),
            )
        )

    return AdminQuotaStats(
        period=period,
        total_recordings=total_recordings,
        total_storage_gb=round(total_storage_bytes / (1024**3), 2),
        total_overage_cost=total_overage_cost,
        plans=plans,
    )

