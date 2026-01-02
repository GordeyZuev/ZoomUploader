"""Middleware для логирования запросов."""

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from logger import get_logger

logger = get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware для логирования HTTP запросов."""

    async def dispatch(self, request: Request, call_next):
        """Обработка запроса с логированием."""
        start_time = time.time()

        # Логируем запрос
        logger.debug(
            f"Request: {request.method} {request.url.path} | "
            f"client={request.client.host if request.client else 'unknown'}"
        )

        # Выполняем запрос
        response = await call_next(request)

        # Логируем ответ
        process_time = time.time() - start_time
        logger.debug(
            f"Response: {request.method} {request.url.path} | status={response.status_code} | time={process_time:.3f}s"
        )

        return response
