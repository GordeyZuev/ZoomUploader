from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class UploadResult:
    """Результат загрузки видео"""

    video_id: str
    video_url: str
    title: str
    upload_time: datetime
    status: str = "uploaded"
    platform: str = ""
    error_message: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class BaseUploader(ABC):
    """Базовый класс загрузчика"""

    def __init__(self, config):
        self.config = config
        self._authenticated = False

    @abstractmethod
    async def authenticate(self) -> bool:
        """Аутентификация на платформе"""
        pass

    def is_authenticated(self) -> bool:
        """Проверка статуса аутентификации"""
        return self._authenticated

    @abstractmethod
    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        progress=None,
        task_id=None,
        **kwargs,
    ) -> UploadResult | None:
        """Загрузка видео"""
        pass

    @abstractmethod
    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Получение информации о видео"""
        pass

    @abstractmethod
    async def delete_video(self, video_id: str) -> bool:
        """Удаление видео"""
        pass

    def validate_file(self, file_path: str) -> tuple[bool, str]:
        """Валидация файла перед загрузкой"""
        import os

        if not os.path.exists(file_path):
            return False, "Файл не существует"

        # Базовая валидация - размер файла
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 5000:  # 5GB лимит по умолчанию
            return False, f"Файл слишком большой: {file_size_mb:.1f}MB"

        return True, "OK"

    def _create_result(
        self,
        video_id: str,
        video_url: str,
        title: str,
        platform: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        """Создание результата загрузки"""
        return UploadResult(
            video_id=video_id,
            video_url=video_url,
            title=title,
            upload_time=datetime.now(),
            platform=platform,
            metadata=metadata or {},
        )

    async def upload_caption(
        self,
        video_id: str,
        caption_path: str,
        language: str = "ru",
        name: str | None = None,
    ) -> bool:
        """
        Загрузка субтитров (по умолчанию не реализована).
        Переопределяется платформенными загрузчиками, которые это поддерживают.
        """
        return False
