"""Middleware для проверки квот пользователей."""

from datetime import datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from database.auth_models import UserQuotaModel


class QuotaMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки квот перед выполнением операций."""

    # Эндпоинты, требующие проверки квот
    QUOTA_ENDPOINTS = {
        "/api/v1/recordings/sync": "recordings",
        "/api/v1/recordings/batch-process": "tasks",
        "/api/v1/recordings/{id}/process": "tasks",
    }

    async def dispatch(self, request: Request, call_next):
        """Проверка квот перед обработкой запроса."""
        # Проверяем только POST запросы к защищенным эндпоинтам
        if request.method == "POST":
            path = request.url.path

            # Проверяем нужна ли проверка квот для этого эндпоинта
            quota_type = self._get_quota_type(path)
            if quota_type:
                # Получаем пользователя из request.state (устанавливается в auth middleware)
                user = getattr(request.state, "user", None)

                if user:
                    # Проверяем квоты
                    await self._check_quotas(request, user.id, quota_type)

        response = await call_next(request)
        return response

    def _get_quota_type(self, path: str) -> str | None:
        """Определить тип квоты для пути."""
        for endpoint_pattern, quota_type in self.QUOTA_ENDPOINTS.items():
            # Простое сопоставление (можно улучшить с regex)
            if endpoint_pattern.replace("{id}", "").rstrip("/") in path:
                return quota_type
        return None

    async def _check_quotas(self, request: Request, user_id: int, quota_type: str):
        """Проверить квоты пользователя."""
        # Получаем сессию БД
        session: AsyncSession = request.state.db_session

        # Получаем квоты пользователя
        result = await session.execute(
            select(UserQuotaModel).where(UserQuotaModel.user_id == user_id)
        )
        quota = result.scalar_one_or_none()

        if not quota:
            # Если квот нет, создаем дефолтные
            quota = await self._create_default_quota(session, user_id)

        # Проверяем не истекли ли квоты
        if quota.quota_reset_at < datetime.utcnow():
            await self._reset_quota(session, quota)

        # Проверяем квоты в зависимости от типа операции
        if quota_type == "recordings":
            if quota.current_recordings_count >= quota.max_recordings_per_month:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Monthly recordings quota exceeded ({quota.max_recordings_per_month})"
                )

        elif quota_type == "tasks":
            if quota.current_tasks_count >= quota.max_concurrent_tasks:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Concurrent tasks quota exceeded ({quota.max_concurrent_tasks})"
                )

    async def _create_default_quota(self, session: AsyncSession, user_id: int) -> UserQuotaModel:
        """Создать дефолтные квоты для пользователя."""
        from dateutil.relativedelta import relativedelta

        quota = UserQuotaModel(
            user_id=user_id,
            max_recordings_per_month=100,
            max_storage_gb=50,
            max_concurrent_tasks=3,
            current_recordings_count=0,
            current_storage_gb=0,
            current_tasks_count=0,
            quota_reset_at=datetime.utcnow() + relativedelta(months=1),
        )
        session.add(quota)
        await session.flush()
        return quota

    async def _reset_quota(self, session: AsyncSession, quota: UserQuotaModel):
        """Сбросить квоты пользователя."""
        from dateutil.relativedelta import relativedelta

        quota.current_recordings_count = 0
        quota.current_storage_gb = 0
        quota.quota_reset_at = datetime.utcnow() + relativedelta(months=1)
        await session.flush()


async def check_storage_quota(session: AsyncSession, user_id: int, required_gb: int) -> bool:
    """Проверить квоту хранилища."""
    result = await session.execute(
        select(UserQuotaModel).where(UserQuotaModel.user_id == user_id)
    )
    quota = result.scalar_one_or_none()

    if not quota:
        return True  # Если квот нет, разрешаем

    return (quota.current_storage_gb + required_gb) <= quota.max_storage_gb


async def increment_recordings_quota(session: AsyncSession, user_id: int):
    """Увеличить счетчик записей."""
    result = await session.execute(
        select(UserQuotaModel).where(UserQuotaModel.user_id == user_id)
    )
    quota = result.scalar_one_or_none()

    if quota:
        quota.current_recordings_count += 1
        await session.flush()


async def increment_tasks_quota(session: AsyncSession, user_id: int):
    """Увеличить счетчик задач."""
    result = await session.execute(
        select(UserQuotaModel).where(UserQuotaModel.user_id == user_id)
    )
    quota = result.scalar_one_or_none()

    if quota:
        quota.current_tasks_count += 1
        await session.flush()


async def decrement_tasks_quota(session: AsyncSession, user_id: int):
    """Уменьшить счетчик задач."""
    result = await session.execute(
        select(UserQuotaModel).where(UserQuotaModel.user_id == user_id)
    )
    quota = result.scalar_one_or_none()

    if quota and quota.current_tasks_count > 0:
        quota.current_tasks_count -= 1
        await session.flush()

