"""Subscription and quota repositories"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from api.schemas.auth import (
    QuotaUsageCreate,
    QuotaUsageInDB,
    QuotaUsageUpdate,
    SubscriptionPlanCreate,
    SubscriptionPlanInDB,
    SubscriptionPlanUpdate,
    UserSubscriptionCreate,
    UserSubscriptionInDB,
    UserSubscriptionUpdate,
)
from database.auth_models import (
    QuotaChangeHistoryModel,
    QuotaUsageModel,
    SubscriptionPlanModel,
    UserSubscriptionModel,
)


class SubscriptionPlanRepository:
    """Repository для работы с тарифными планами."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, plan_id: int) -> SubscriptionPlanInDB | None:
        """Получить план по ID."""
        result = await self.session.execute(
            select(SubscriptionPlanModel).where(SubscriptionPlanModel.id == plan_id)
        )
        db_plan = result.scalars().first()
        if not db_plan:
            return None
        return SubscriptionPlanInDB.model_validate(db_plan)

    async def get_by_name(self, name: str) -> SubscriptionPlanInDB | None:
        """Получить план по имени."""
        result = await self.session.execute(
            select(SubscriptionPlanModel).where(SubscriptionPlanModel.name == name)
        )
        db_plan = result.scalars().first()
        if not db_plan:
            return None
        return SubscriptionPlanInDB.model_validate(db_plan)

    async def get_all(self, active_only: bool = True) -> list[SubscriptionPlanInDB]:
        """Получить все планы."""
        query = select(SubscriptionPlanModel).order_by(SubscriptionPlanModel.sort_order)
        if active_only:
            query = query.where(SubscriptionPlanModel.is_active == True)  # noqa: E712

        result = await self.session.execute(query)
        db_plans = result.scalars().all()
        return [SubscriptionPlanInDB.model_validate(plan) for plan in db_plans]

    async def create(self, plan_data: SubscriptionPlanCreate) -> SubscriptionPlanInDB:
        """Создать новый план."""
        plan = SubscriptionPlanModel(**plan_data.model_dump())
        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)
        return SubscriptionPlanInDB.model_validate(plan)

    async def update(self, plan_id: int, plan_data: SubscriptionPlanUpdate) -> SubscriptionPlanInDB | None:
        """Обновить план."""
        result = await self.session.execute(
            select(SubscriptionPlanModel).where(SubscriptionPlanModel.id == plan_id)
        )
        db_plan = result.scalars().first()
        if not db_plan:
            return None

        update_dict = plan_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_plan, key, value)

        db_plan.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(db_plan)
        return SubscriptionPlanInDB.model_validate(db_plan)

    async def delete(self, plan_id: int) -> bool:
        """Удалить план (soft delete - деактивация)."""
        result = await self.session.execute(
            select(SubscriptionPlanModel).where(SubscriptionPlanModel.id == plan_id)
        )
        db_plan = result.scalars().first()
        if not db_plan:
            return False

        db_plan.is_active = False
        db_plan.updated_at = datetime.utcnow()
        await self.session.commit()
        return True


class UserSubscriptionRepository:
    """Repository для работы с подписками пользователей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> UserSubscriptionInDB | None:
        """Получить подписку пользователя."""
        result = await self.session.execute(
            select(UserSubscriptionModel)
            .options(joinedload(UserSubscriptionModel.plan))
            .where(UserSubscriptionModel.user_id == user_id)
        )
        db_subscription = result.scalars().first()
        if not db_subscription:
            return None
        return UserSubscriptionInDB.model_validate(db_subscription)

    async def get_by_id(self, subscription_id: int) -> UserSubscriptionInDB | None:
        """Получить подписку по ID."""
        result = await self.session.execute(
            select(UserSubscriptionModel)
            .options(joinedload(UserSubscriptionModel.plan))
            .where(UserSubscriptionModel.id == subscription_id)
        )
        db_subscription = result.scalars().first()
        if not db_subscription:
            return None
        return UserSubscriptionInDB.model_validate(db_subscription)

    async def create(self, subscription_data: UserSubscriptionCreate) -> UserSubscriptionInDB:
        """Создать подписку для пользователя."""
        subscription = UserSubscriptionModel(**subscription_data.model_dump(exclude_none=True))
        self.session.add(subscription)
        await self.session.commit()
        await self.session.refresh(subscription)

        # Reload with plan relationship
        result = await self.session.execute(
            select(UserSubscriptionModel)
            .options(joinedload(UserSubscriptionModel.plan))
            .where(UserSubscriptionModel.id == subscription.id)
        )
        db_subscription = result.scalars().first()
        return UserSubscriptionInDB.model_validate(db_subscription)

    async def update(
        self, user_id: int, subscription_data: UserSubscriptionUpdate
    ) -> UserSubscriptionInDB | None:
        """Обновить подписку пользователя."""
        result = await self.session.execute(
            select(UserSubscriptionModel)
            .options(joinedload(UserSubscriptionModel.plan))
            .where(UserSubscriptionModel.user_id == user_id)
        )
        db_subscription = result.scalars().first()
        if not db_subscription:
            return None

        # Store old values for history
        old_plan_id = db_subscription.plan_id

        update_dict = subscription_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_subscription, key, value)

        db_subscription.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(db_subscription)

        # Log change to history if plan changed
        if subscription_data.plan_id and subscription_data.plan_id != old_plan_id:
            await self._log_plan_change(
                user_id=user_id,
                old_plan_id=old_plan_id,
                new_plan_id=subscription_data.plan_id,
                changed_by=subscription_data.modified_by,
                notes=subscription_data.notes,
            )

        return UserSubscriptionInDB.model_validate(db_subscription)

    async def delete(self, user_id: int) -> bool:
        """Удалить подписку пользователя."""
        result = await self.session.execute(
            select(UserSubscriptionModel).where(UserSubscriptionModel.user_id == user_id)
        )
        db_subscription = result.scalars().first()
        if not db_subscription:
            return False

        await self.session.delete(db_subscription)
        await self.session.commit()
        return True

    async def _log_plan_change(
        self,
        user_id: int,
        old_plan_id: int,
        new_plan_id: int,
        changed_by: int | None = None,
        notes: str | None = None,
    ):
        """Записать изменение плана в историю."""
        history = QuotaChangeHistoryModel(
            user_id=user_id,
            changed_by=changed_by,
            change_type="plan_change",
            old_plan_id=old_plan_id,
            new_plan_id=new_plan_id,
            notes=notes,
        )
        self.session.add(history)
        await self.session.commit()


class QuotaUsageRepository:
    """Repository для работы с использованием квот."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_and_period(self, user_id: int, period: int) -> QuotaUsageInDB | None:
        """Получить использование квот за период."""
        result = await self.session.execute(
            select(QuotaUsageModel).where(
                QuotaUsageModel.user_id == user_id, QuotaUsageModel.period == period
            )
        )
        db_usage = result.scalars().first()
        if not db_usage:
            return None
        return QuotaUsageInDB.model_validate(db_usage)

    async def get_current_period(self, user_id: int) -> QuotaUsageInDB | None:
        """Получить использование за текущий период."""
        current_period = int(datetime.now().strftime("%Y%m"))
        return await self.get_by_user_and_period(user_id, current_period)

    async def get_history(self, user_id: int, limit: int = 12) -> list[QuotaUsageInDB]:
        """Получить историю использования."""
        result = await self.session.execute(
            select(QuotaUsageModel)
            .where(QuotaUsageModel.user_id == user_id)
            .order_by(QuotaUsageModel.period.desc())
            .limit(limit)
        )
        db_usages = result.scalars().all()
        return [QuotaUsageInDB.model_validate(usage) for usage in db_usages]

    async def create(self, usage_data: QuotaUsageCreate) -> QuotaUsageInDB:
        """Создать запись использования."""
        usage = QuotaUsageModel(**usage_data.model_dump())
        self.session.add(usage)
        await self.session.commit()
        await self.session.refresh(usage)
        return QuotaUsageInDB.model_validate(usage)

    async def update(
        self, user_id: int, period: int, usage_data: QuotaUsageUpdate
    ) -> QuotaUsageInDB | None:
        """Обновить использование."""
        result = await self.session.execute(
            select(QuotaUsageModel).where(
                QuotaUsageModel.user_id == user_id, QuotaUsageModel.period == period
            )
        )
        db_usage = result.scalars().first()
        if not db_usage:
            return None

        update_dict = usage_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_usage, key, value)

        db_usage.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(db_usage)
        return QuotaUsageInDB.model_validate(db_usage)

    async def increment_recordings(self, user_id: int, period: int, count: int = 1) -> QuotaUsageInDB:
        """Увеличить счетчик записей (upsert)."""
        result = await self.session.execute(
            select(QuotaUsageModel).where(
                QuotaUsageModel.user_id == user_id, QuotaUsageModel.period == period
            )
        )
        db_usage = result.scalars().first()

        if db_usage:
            db_usage.recordings_count += count
            db_usage.updated_at = datetime.utcnow()
        else:
            db_usage = QuotaUsageModel(
                user_id=user_id, period=period, recordings_count=count
            )
            self.session.add(db_usage)

        await self.session.commit()
        await self.session.refresh(db_usage)
        return QuotaUsageInDB.model_validate(db_usage)

    async def increment_storage(self, user_id: int, period: int, bytes_added: int) -> QuotaUsageInDB:
        """Увеличить счетчик хранилища."""
        result = await self.session.execute(
            select(QuotaUsageModel).where(
                QuotaUsageModel.user_id == user_id, QuotaUsageModel.period == period
            )
        )
        db_usage = result.scalars().first()

        if db_usage:
            db_usage.storage_bytes += bytes_added
            db_usage.updated_at = datetime.utcnow()
        else:
            db_usage = QuotaUsageModel(
                user_id=user_id, period=period, storage_bytes=bytes_added
            )
            self.session.add(db_usage)

        await self.session.commit()
        await self.session.refresh(db_usage)
        return QuotaUsageInDB.model_validate(db_usage)

    async def set_concurrent_tasks(self, user_id: int, period: int, count: int) -> QuotaUsageInDB:
        """Установить счетчик одновременных задач."""
        result = await self.session.execute(
            select(QuotaUsageModel).where(
                QuotaUsageModel.user_id == user_id, QuotaUsageModel.period == period
            )
        )
        db_usage = result.scalars().first()

        if db_usage:
            db_usage.concurrent_tasks_count = count
            db_usage.updated_at = datetime.utcnow()
        else:
            db_usage = QuotaUsageModel(
                user_id=user_id, period=period, concurrent_tasks_count=count
            )
            self.session.add(db_usage)

        await self.session.commit()
        await self.session.refresh(db_usage)
        return QuotaUsageInDB.model_validate(db_usage)

