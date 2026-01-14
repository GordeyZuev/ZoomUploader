"""Global error handling"""

import os

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from api.shared.exceptions import APIException
from logger import get_logger

logger = get_logger()

DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Глобальный обработчик исключений."""
    try:
        exc_str = str(exc)
    except Exception:
        exc_str = repr(exc)

    logger.error("Unhandled exception: {}", exc_str, exc_info=exc)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": exc_str if DEBUG else "An error occurred",
        },
    )


async def api_exception_handler(request: Request, exc: APIException) -> JSONResponse:
    """Обработчик API исключений."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Обработчик ошибок валидации."""
    errors = []
    for error in exc.errors():
        error_dict = {
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
            "input": error.get("input"),
        }
        if "ctx" in error and error["ctx"]:
            error_dict["ctx"] = {k: str(v) for k, v in error["ctx"].items()}
        errors.append(error_dict)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation error",
            "detail": errors,
        },
    )


async def response_validation_exception_handler(request: Request, exc: ResponseValidationError) -> JSONResponse:
    """Обработчик ошибок валидации response (внутренние ошибки сервера)."""
    logger.error("Response validation error: {}", exc, exc_info=exc)

    # Extract validation errors
    errors = []
    for error in exc.errors():
        error_dict = {
            "type": error.get("type"),
            "loc": error.get("loc"),
            "msg": error.get("msg"),
        }
        if "input" in error:
            # Don't expose full input in production
            error_dict["input_summary"] = f"{type(error['input']).__name__}" if not DEBUG else error["input"]
        if "ctx" in error and error["ctx"]:
            error_dict["ctx"] = {k: str(v) for k, v in error["ctx"].items()}
        errors.append(error_dict)

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": "Response validation failed" if not DEBUG else errors,
            "message": "The server returned invalid data. Please contact support.",
        },
    )


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Обработчик ошибок SQLAlchemy."""
    logger.error("Database error: {}", exc, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Database error",
            "detail": "An error occurred while accessing the database",
        },
    )
