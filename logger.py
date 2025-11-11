import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def setup_logger(log_level: str | None = None, log_file: str | None = None) -> None:
    """Настройка логгера."""
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "INFO")

    env_log_file = os.getenv("LOG_FILE")
    error_log_file = os.getenv("ERROR_LOG_FILE")
    if log_file is None:
        log_file = env_log_file

    logger.remove()
    logger.configure(extra={"module": "app"})

    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[module]: <25}</cyan> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )

    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
        "{extra[module]: <25} | {name}:{function}:{line} - {message}"
    )

    logger.add(
        sys.stderr,
        format=console_format,
        level=log_level,
        colorize=True,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_file,
            format=file_format,
            level=log_level,
            rotation="10 MB",
            retention="7 days",
            compression="zip",
        )

    if error_log_file:
        err_path = Path(error_log_file)
        err_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            error_log_file,
            format=file_format,
            level="ERROR",
            rotation="10 MB",
            retention="14 days",
            compression="zip",
        )


def get_logger(module_name: str | None = None):
    """Получение настроенного логгера."""
    if module_name:
        return logger.bind(module=module_name)
    return logger


def format_log(message: str, **details: Any) -> str:
    """Формирование единообразного текста лог-сообщения."""
    if not details:
        return message
    serialized_details: list[str] = []
    for key, value in details.items():
        serialized_details.append(f"{key}={value}")
    return f"{message} | " + " | ".join(serialized_details)


setup_logger()
