"""
Утилиты для красивых спиннеров и прогресс-баров
"""

from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


class SpinnerManager:
    """Менеджер для красивых спиннеров и прогресс-баров"""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    @asynccontextmanager
    async def spinner(self, message: str, style: str = "blue"):
        """Контекстный менеджер для спиннера"""
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[{style}]{message}[/{style}]"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("", total=None)
            try:
                yield progress, task
            finally:
                progress.stop()

    @asynccontextmanager
    async def progress_bar(self, message: str, total: int, style: str = "green"):
        """Контекстный менеджер для прогресс-бара"""
        with Progress(
            TextColumn(f"[{style}]{message}[/{style}]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total})"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("", total=total)
            try:
                yield progress, task
            finally:
                progress.stop()

    async def run_with_spinner(self, message: str, coro: Callable, style: str = "blue") -> Any:
        """Запуск корутины со спиннером"""
        async with self.spinner(message, style) as (progress, task):
            return await coro()

    def print_success(self, message: str):
        """Печать сообщения об успехе"""
        self.console.print(f"✅ {message}")

    def print_error(self, message: str):
        """Печать сообщения об ошибке"""
        self.console.print(f"❌ {message}")

    def print_info(self, message: str):
        """Печать информационного сообщения"""
        self.console.print(f"ℹ️ {message}")

    def print_warning(self, message: str):
        """Печать предупреждения"""
        self.console.print(f"⚠️ {message}")


spinner_manager = SpinnerManager()
