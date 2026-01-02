"""Middleware для rate limiting."""

import time
from collections import defaultdict
from collections.abc import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api.config import get_settings
from logger import get_logger

logger = get_logger()
settings = get_settings()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware для ограничения частоты запросов (rate limiting).

    Использует простой in-memory счетчик запросов по IP адресу.
    Для production лучше использовать Redis.
    """

    def __init__(self, app, per_minute: int = 60, per_hour: int = 1000):
        """
        Инициализация middleware.

        Args:
            app: FastAPI приложение
            per_minute: Максимум запросов в минуту
            per_hour: Максимум запросов в час
        """
        super().__init__(app)
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.minute_requests = defaultdict(list)
        self.hour_requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Обработка запроса с проверкой rate limit.

        Args:
            request: HTTP запрос
            call_next: Следующий обработчик

        Returns:
            HTTP ответ
        """
        if not settings.rate_limit_enabled:
            return await call_next(request)

        # Пропускаем health check
        if request.url.path == "/health":
            return await call_next(request)

        # Получаем IP клиента
        client_ip = request.client.host if request.client else "unknown"

        # Текущее время
        current_time = time.time()
        minute_ago = current_time - 60
        hour_ago = current_time - 3600

        # Очистка старых записей
        self.minute_requests[client_ip] = [t for t in self.minute_requests[client_ip] if t > minute_ago]
        self.hour_requests[client_ip] = [t for t in self.hour_requests[client_ip] if t > hour_ago]

        # Проверка лимитов
        minute_count = len(self.minute_requests[client_ip])
        hour_count = len(self.hour_requests[client_ip])

        if minute_count >= self.per_minute:
            logger.warning(
                f"Rate limit exceeded (per minute): ip={client_ip} | requests={minute_count}/{self.per_minute}"
            )
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Rate limit exceeded: {self.per_minute} requests per minute",
                    "retry_after": 60,
                },
                headers={"Retry-After": "60"},
            )

        if hour_count >= self.per_hour:
            logger.warning(f"Rate limit exceeded (per hour): ip={client_ip} | requests={hour_count}/{self.per_hour}")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": f"Rate limit exceeded: {self.per_hour} requests per hour",
                    "retry_after": 3600,
                },
                headers={"Retry-After": "3600"},
            )

        # Добавляем текущий запрос
        self.minute_requests[client_ip].append(current_time)
        self.hour_requests[client_ip].append(current_time)

        # Выполняем запрос
        response = await call_next(request)

        # Добавляем заголовки с информацией о лимитах
        response.headers["X-RateLimit-Limit-Minute"] = str(self.per_minute)
        response.headers["X-RateLimit-Remaining-Minute"] = str(max(0, self.per_minute - minute_count - 1))
        response.headers["X-RateLimit-Limit-Hour"] = str(self.per_hour)
        response.headers["X-RateLimit-Remaining-Hour"] = str(max(0, self.per_hour - hour_count - 1))

        return response
