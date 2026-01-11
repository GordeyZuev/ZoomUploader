"""Middleware для проверки квот пользователей."""

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from api.services.quota_service import QuotaService


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
        quota_service = QuotaService(session)

        # Проверяем квоты в зависимости от типа операции
        if quota_type == "recordings":
            allowed, error_msg = await quota_service.check_recordings_quota(user_id)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=error_msg or "Monthly recordings quota exceeded"
                )

        elif quota_type == "tasks":
            allowed, error_msg = await quota_service.check_concurrent_tasks_quota(user_id)
            if not allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=error_msg or "Concurrent tasks quota exceeded"
                )


async def check_storage_quota(session: AsyncSession, user_id: int, required_bytes: int) -> bool:
    """Проверить квоту хранилища."""
    quota_service = QuotaService(session)
    allowed, _ = await quota_service.check_storage_quota(user_id, required_bytes)
    return allowed


async def increment_recordings_quota(session: AsyncSession, user_id: int):
    """Увеличить счетчик записей."""
    quota_service = QuotaService(session)
    await quota_service.track_recording_created(user_id)


async def increment_tasks_quota(session: AsyncSession, user_id: int, count: int = 1):
    """Увеличить счетчик задач."""
    from datetime import datetime

    quota_service = QuotaService(session)
    current_period = int(datetime.now().strftime("%Y%m"))
    usage = await quota_service.usage_repo.get_by_user_and_period(user_id, current_period)
    current_count = usage.concurrent_tasks_count if usage else 0
    await quota_service.set_concurrent_tasks_count(user_id, current_count + count)


async def decrement_tasks_quota(session: AsyncSession, user_id: int, count: int = 1):
    """Уменьшить счетчик задач."""
    from datetime import datetime

    quota_service = QuotaService(session)
    current_period = int(datetime.now().strftime("%Y%m"))
    usage = await quota_service.usage_repo.get_by_user_and_period(user_id, current_period)
    current_count = usage.concurrent_tasks_count if usage else 0
    new_count = max(0, current_count - count)
    await quota_service.set_concurrent_tasks_count(user_id, new_count)

