"""FastAPI приложение."""

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from api.config import get_settings
from api.middleware.error_handler import (
    api_exception_handler,
    global_exception_handler,
    sqlalchemy_exception_handler,
    validation_exception_handler,
)
from api.middleware.logging import LoggingMiddleware
from api.middleware.rate_limit import RateLimitMiddleware
from api.routers import (
    auth,
    configs,
    credentials,
    health,
    input_sources,
    output_presets,
    recordings,
    tasks,
    templates,
)
from api.shared.exceptions import APIException

settings = get_settings()

app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=settings.api_description,
    docs_url=settings.docs_url,
    redoc_url=settings.redoc_url,
    openapi_url=settings.openapi_url,
)

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
app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Routers
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(credentials.router)
app.include_router(recordings.router)
app.include_router(tasks.router)
# New template system routers
app.include_router(templates.router)
app.include_router(input_sources.router)
app.include_router(output_presets.router)
app.include_router(configs.router)


@app.get("/")
async def root():
    """Корневой endpoint."""
    return {
        "message": "Zoom Publishing Platform API",
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
