"""FastAPI приложение."""

import subprocess

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

# Явно импортируем Celery задачи чтобы они зарегистрировались в API сервере
import api.tasks.automation  # noqa: F401
import api.tasks.maintenance  # noqa: F401
import api.tasks.processing  # noqa: F401
import api.tasks.sync_tasks  # noqa: F401
import api.tasks.template  # noqa: F401
import api.tasks.upload  # noqa: F401
from api.config import get_settings
from api.middleware.error_handler import (
    api_exception_handler,
    global_exception_handler,
    response_validation_exception_handler,
    sqlalchemy_exception_handler,
    validation_exception_handler,
)
from api.middleware.logging import LoggingMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.routers import (
    admin,
    auth,
    automation,
    credentials,
    health,
    input_sources,
    oauth,
    output_presets,
    recordings,
    tasks,
    templates,
    thumbnails,
    user_config,
    users,
)
from api.shared.exceptions import APIException
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger

settings = get_settings()
logger = get_logger()

app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=settings.api_description,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
    openapi_url=settings.openapi_url,
)


@app.on_event("startup")
async def startup_event():
    """Инициализация БД при запуске приложения."""
    try:
        logger.info("🚀 Инициализация базы данных...")

        # Создаем БД, если её нет
        db_config = DatabaseConfig.from_env()
        db_manager = DatabaseManager(db_config)
        await db_manager.create_database_if_not_exists()
        await db_manager.close()

        logger.info("✅ База данных создана (если не существовала)")

        # Применяем миграции Alembic
        logger.info("🔄 Применение миграций Alembic...")
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            logger.info("✅ Миграции применены успешно")
        else:
            logger.error(f"❌ Ошибка применения миграций: {result.stderr}")
            # Не падаем, чтобы приложение могло запуститься для диагностики

    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        # Не падаем, чтобы приложение могло запуститься для диагностики

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    per_minute=settings.rate_limit_per_minute,
    per_hour=settings.rate_limit_per_hour,
)

# Logging middleware
app.add_middleware(LoggingMiddleware)

# Exception handlers
app.add_exception_handler(APIException, api_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(ResponseValidationError, response_validation_exception_handler)
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(user_config.router)
app.include_router(credentials.router)
app.include_router(oauth.router)
app.include_router(recordings.router)
app.include_router(tasks.router)
# New template system routers
app.include_router(templates.router)
app.include_router(input_sources.router)
app.include_router(output_presets.router)
app.include_router(thumbnails.router)
# Automation router
app.include_router(automation.router)
# Admin router
app.include_router(admin.router)


@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "message": "LEAP API - Lecture Enhancement & Automation Platform",
        "version": settings.api_version,
        "docs": settings.docs_url,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
