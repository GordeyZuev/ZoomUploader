"""Quota and subscription service"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.subscription_repos import (
    QuotaUsageRepository,
    SubscriptionPlanRepository,
    UserSubscriptionRepository,
)
from api.schemas.auth import (
    QuotaStatusResponse,
    QuotaUsageResponse,
    SubscriptionPlanResponse,
    UserSubscriptionResponse,
)


class QuotaService:
    """Сервис для проверки и управления квотами."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.subscription_repo = UserSubscriptionRepository(session)
        self.plan_repo = SubscriptionPlanRepository(session)
        self.usage_repo = QuotaUsageRepository(session)

    # ========================================
    # EFFECTIVE QUOTAS (with custom overrides)
    # ========================================

    async def get_effective_quotas(self, user_id: int) -> dict[str, int | None]:
        """
        Получить эффективные квоты пользователя (с учетом custom overrides).

        Returns:
            {
                "max_recordings_per_month": 100,
                "max_storage_gb": 50,
                "max_concurrent_tasks": 3,
                "max_automation_jobs": 5,
                "min_automation_interval_hours": 1
            }
        """
        subscription = await self.subscription_repo.get_by_user_id(user_id)
        if not subscription:
            # No subscription - return default Free plan limits
            free_plan = await self.plan_repo.get_by_name("free")
            if not free_plan:
                raise ValueError("Free plan not found in database")
            return {
                "max_recordings_per_month": free_plan.included_recordings_per_month,
                "max_storage_gb": free_plan.included_storage_gb,
                "max_concurrent_tasks": free_plan.max_concurrent_tasks,
                "max_automation_jobs": free_plan.max_automation_jobs,
                "min_automation_interval_hours": free_plan.min_automation_interval_hours,
            }

        plan = await self.plan_repo.get_by_id(subscription.plan_id)
        if not plan:
            raise ValueError(f"Plan {subscription.plan_id} not found")

        # Apply custom overrides
        return {
            "max_recordings_per_month": subscription.custom_max_recordings_per_month
            or plan.included_recordings_per_month,
            "max_storage_gb": subscription.custom_max_storage_gb or plan.included_storage_gb,
            "max_concurrent_tasks": subscription.custom_max_concurrent_tasks or plan.max_concurrent_tasks,
            "max_automation_jobs": subscription.custom_max_automation_jobs or plan.max_automation_jobs,
            "min_automation_interval_hours": subscription.custom_min_automation_interval_hours
            or plan.min_automation_interval_hours,
        }

    # ========================================
    # QUOTA CHECKS
    # ========================================

    async def check_recordings_quota(self, user_id: int) -> tuple[bool, str | None]:
        """
        Проверить квоту на создание записи.

        Returns:
            (allowed, error_message)
        """
        quotas = await self.get_effective_quotas(user_id)
        max_recordings = quotas["max_recordings_per_month"]

        # NULL = unlimited
        if max_recordings is None:
            return True, None

        # Get current usage
        current_period = int(datetime.now().strftime("%Y%m"))
        usage = await self.usage_repo.get_by_user_and_period(user_id, current_period)
        current_count = usage.recordings_count if usage else 0

        if current_count >= max_recordings:
            subscription = await self.subscription_repo.get_by_user_id(user_id)

            # Check if Pay-as-you-go is enabled
            if subscription and subscription.pay_as_you_go_enabled:
                # Check overage limit
                if subscription.pay_as_you_go_monthly_limit:
                    overage_cost = usage.overage_cost if usage else Decimal("0")
                    if overage_cost >= subscription.pay_as_you_go_monthly_limit:
                        return (
                            False,
                            f"Достигнут лимит overage ${subscription.pay_as_you_go_monthly_limit}",
                        )
                # Allow with overage
                return True, None

            return False, f"Превышена квота записей: {max_recordings} в месяц"

        return True, None

    async def check_storage_quota(self, user_id: int, bytes_to_add: int) -> tuple[bool, str | None]:
        """
        Проверить квоту на хранилище.

        Returns:
            (allowed, error_message)
        """
        quotas = await self.get_effective_quotas(user_id)
        max_storage_gb = quotas["max_storage_gb"]

        # NULL = unlimited
        if max_storage_gb is None:
            return True, None

        # Get current usage
        current_period = int(datetime.now().strftime("%Y%m"))
        usage = await self.usage_repo.get_by_user_and_period(user_id, current_period)
        current_bytes = usage.storage_bytes if usage else 0

        max_bytes = max_storage_gb * 1024 * 1024 * 1024
        if current_bytes + bytes_to_add > max_bytes:
            return False, f"Превышена квота хранилища: {max_storage_gb} GB"

        return True, None

    async def check_concurrent_tasks_quota(self, user_id: int) -> tuple[bool, str | None]:
        """
        Проверить квоту на одновременные задачи.

        Returns:
            (allowed, error_message)
        """
        quotas = await self.get_effective_quotas(user_id)
        max_tasks = quotas["max_concurrent_tasks"]

        # NULL = unlimited
        if max_tasks is None:
            return True, None

        # Get current usage
        current_period = int(datetime.now().strftime("%Y%m"))
        usage = await self.usage_repo.get_by_user_and_period(user_id, current_period)
        current_tasks = usage.concurrent_tasks_count if usage else 0

        if current_tasks >= max_tasks:
            return False, f"Превышен лимит одновременных задач: {max_tasks}"

        return True, None

    async def check_automation_jobs_quota(self, user_id: int) -> tuple[bool, str | None]:
        """
        Проверить квоту на automation jobs.

        Returns:
            (allowed, error_message)
        """
        quotas = await self.get_effective_quotas(user_id)
        max_jobs = quotas["max_automation_jobs"]

        # NULL = unlimited
        if max_jobs is None:
            return True, None

        # Count active automation jobs (this would need to query automation_jobs table)
        # For now, placeholder
        # TODO: Implement actual count from automation_jobs table
        current_jobs = 0

        if current_jobs >= max_jobs:
            return False, f"Превышен лимит automation jobs: {max_jobs}"

        return True, None

    # ========================================
    # USAGE TRACKING
    # ========================================

    async def track_recording_created(self, user_id: int) -> None:
        """Записать создание новой записи."""
        current_period = int(datetime.now().strftime("%Y%m"))
        await self.usage_repo.increment_recordings(user_id, current_period, count=1)

    async def track_storage_added(self, user_id: int, bytes_added: int) -> None:
        """Записать добавление данных в хранилище."""
        current_period = int(datetime.now().strftime("%Y%m"))
        await self.usage_repo.increment_storage(user_id, current_period, bytes_added)

    async def track_storage_removed(self, user_id: int, bytes_removed: int) -> None:
        """Записать удаление данных из хранилища."""
        current_period = int(datetime.now().strftime("%Y%m"))
        await self.usage_repo.increment_storage(user_id, current_period, -bytes_removed)

    async def set_concurrent_tasks_count(self, user_id: int, count: int) -> None:
        """Установить текущее количество одновременных задач."""
        current_period = int(datetime.now().strftime("%Y%m"))
        await self.usage_repo.set_concurrent_tasks(user_id, current_period, count)

    # ========================================
    # QUOTA STATUS
    # ========================================

    async def get_quota_status(self, user_id: int) -> QuotaStatusResponse:
        """
        Получить полный статус квот пользователя.

        Returns:
            QuotaStatusResponse with subscription, usage, and quota status
        """
        # Get subscription with plan
        subscription = await self.subscription_repo.get_by_user_id(user_id)
        if not subscription:
            raise ValueError(f"No subscription found for user {user_id}")

        plan = await self.plan_repo.get_by_id(subscription.plan_id)
        if not plan:
            raise ValueError(f"Plan {subscription.plan_id} not found")

        # Get effective quotas
        quotas = await self.get_effective_quotas(user_id)

        # Get current usage
        current_period = int(datetime.now().strftime("%Y%m"))
        usage = await self.usage_repo.get_by_user_and_period(user_id, current_period)

        # Build subscription response
        subscription_response = UserSubscriptionResponse(
            id=subscription.id,
            user_id=subscription.user_id,
            plan=SubscriptionPlanResponse.model_validate(plan),
            custom_max_recordings_per_month=subscription.custom_max_recordings_per_month,
            custom_max_storage_gb=subscription.custom_max_storage_gb,
            custom_max_concurrent_tasks=subscription.custom_max_concurrent_tasks,
            custom_max_automation_jobs=subscription.custom_max_automation_jobs,
            custom_min_automation_interval_hours=subscription.custom_min_automation_interval_hours,
            effective_max_recordings_per_month=quotas["max_recordings_per_month"],
            effective_max_storage_gb=quotas["max_storage_gb"],
            effective_max_concurrent_tasks=quotas["max_concurrent_tasks"],
            effective_max_automation_jobs=quotas["max_automation_jobs"],
            effective_min_automation_interval_hours=quotas["min_automation_interval_hours"],
            pay_as_you_go_enabled=subscription.pay_as_you_go_enabled,
            pay_as_you_go_monthly_limit=subscription.pay_as_you_go_monthly_limit,
            starts_at=subscription.starts_at,
            expires_at=subscription.expires_at,
        )

        # Build usage response
        usage_response = None
        if usage:
            usage_response = QuotaUsageResponse(
                period=usage.period,
                recordings_count=usage.recordings_count,
                storage_gb=usage.storage_bytes / (1024**3),
                concurrent_tasks_count=usage.concurrent_tasks_count,
                overage_recordings_count=usage.overage_recordings_count,
                overage_cost=usage.overage_cost,
            )

        # Calculate quota status
        recordings_used = usage.recordings_count if usage else 0
        storage_bytes_used = usage.storage_bytes if usage else 0
        tasks_used = usage.concurrent_tasks_count if usage else 0

        max_recordings = quotas["max_recordings_per_month"]
        max_storage_gb = quotas["max_storage_gb"]
        max_tasks = quotas["max_concurrent_tasks"]
        max_jobs = quotas["max_automation_jobs"]

        return QuotaStatusResponse(
            subscription=subscription_response,
            current_usage=usage_response,
            recordings={
                "used": recordings_used,
                "limit": max_recordings,
                "available": max_recordings - recordings_used if max_recordings else None,
            },
            storage={
                "used_gb": storage_bytes_used / (1024**3),
                "limit_gb": max_storage_gb,
                "available_gb": (max_storage_gb - storage_bytes_used / (1024**3)) if max_storage_gb else None,
            },
            concurrent_tasks={
                "used": tasks_used,
                "limit": max_tasks,
                "available": max_tasks - tasks_used if max_tasks else None,
            },
            automation_jobs={
                "used": 0,  # TODO: Get from automation_jobs table
                "limit": max_jobs,
                "available": max_jobs if max_jobs else None,
            },
            is_overage_enabled=subscription.pay_as_you_go_enabled,
            overage_cost_this_month=usage.overage_cost if usage else Decimal("0"),
            overage_limit=subscription.pay_as_you_go_monthly_limit,
        )
