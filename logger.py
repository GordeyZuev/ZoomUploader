import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

load_dotenv()


def setup_logger(log_level: str = None, log_file: str = None):
    """Настройка логгера."""
    if log_level is None:
        log_level = os.getenv("LOG_LEVEL", "ERROR")

    env_log_file = os.getenv("LOG_FILE")
    error_log_file = os.getenv("ERROR_LOG_FILE")
    if log_file is None:
        log_file = env_log_file

    logger.remove()

    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
    )

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        logger.add(
            log_file,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
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
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            level="ERROR",
            rotation="10 MB",
            retention="14 days",
            compression="zip",
        )


def get_logger():
    """Получение настроенного логгера."""
    return logger


setup_logger()
