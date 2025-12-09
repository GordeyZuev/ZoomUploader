import asyncio
from datetime import datetime
from typing import Any

from logger import get_logger

from ..config_factory import UploadConfig
from ..platforms.vk import VKUploader
from ..platforms.youtube import YouTubeUploader
from .base import BaseUploader, UploadResult

logger = get_logger()


class UploadManager:
    """Универсальный менеджер для загрузки видео на различные платформы."""

    def __init__(self, config: UploadConfig):
        self.config = config
        self.uploaders: dict[str, BaseUploader] = {}
        self._initialize_uploaders()

    def _initialize_uploaders(self):
        """Инициализация загрузчиков."""
        if self.config.youtube:
            self.uploaders['youtube'] = YouTubeUploader(self.config.youtube)
        if self.config.vk:
            self.uploaders['vk'] = VKUploader(self.config.vk)

    def add_uploader(self, platform: str, uploader: BaseUploader):
        """Добавление загрузчика."""
        self.uploaders[platform] = uploader

    def get_uploader(self, platform: str) -> BaseUploader | None:
        """Получение загрузчика по платформе."""
        return self.uploaders.get(platform)

    def get_available_platforms(self) -> list[str]:
        """Получение списка доступных платформ."""
        return list(self.uploaders.keys())

    async def upload_to_platform(
        self,
        platform: str,
        video_path: str,
        title: str,
        description: str = "",
        progress=None,
        task_id=None,
        **kwargs,
    ) -> UploadResult | None:
        """Загрузка видео на конкретную платформу."""

        uploader = self.get_uploader(platform)
        if not uploader:
            logger.error(f"❌ Загрузчик для платформы {platform} не найден")
            return None

        is_valid, message = uploader.validate_file(video_path)
        if not is_valid:
            logger.error(f"❌ Файл не прошел валидацию: {message}")
            return None

        for attempt in range(self.config.retry_attempts):
            try:
                logger.info(
                    f"📤 Попытка {attempt + 1}/{self.config.retry_attempts} загрузки на {platform}"
                )

                result = await uploader.upload_video(
                    video_path=video_path,
                    title=title,
                    description=description,
                    progress=progress,
                    task_id=task_id,
                    **kwargs,
                )

                if result:
                    return result

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки на {platform} (попытка {attempt + 1}): {e}")

                if attempt < self.config.retry_attempts - 1:
                    logger.info(
                        f"⏳ Ожидание {self.config.retry_delay} секунд перед повторной попыткой..."
                    )
                    await asyncio.sleep(self.config.retry_delay)

        logger.error(
            f"❌ Не удалось загрузить видео на {platform} после {self.config.retry_attempts} попыток"
        )
        return None

    async def upload_caption(
        self,
        platform: str,
        video_id: str,
        caption_path: str,
        language: str = "ru",
        name: str | None = None,
    ) -> bool:
        """Загрузка субтитров, если платформа поддерживает."""
        uploader = self.get_uploader(platform)
        if not uploader:
            logger.error(f"❌ Загрузчик для платформы {platform} не найден")
            return False

        if not hasattr(uploader, "upload_caption"):
            logger.info(f"ℹ️ Платформа {platform} не поддерживает загрузку субтитров")
            return False

        try:
            return bool(
                await uploader.upload_caption(
                    video_id=video_id,
                    caption_path=caption_path,
                    language=language,
                    name=name,
                )
            )
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки субтитров на {platform}: {e}")
            return False

    async def upload_to_all_platforms(
        self, video_path: str, title: str, description: str = "", **kwargs
    ) -> dict[str, UploadResult | None]:
        """Загрузка видео на все настроенные платформы (параллельно)."""

        platforms = self.get_available_platforms()
        if not platforms:
            return {}

        # Создаем задачи для параллельной загрузки
        tasks = {
            platform: self.upload_to_platform(
                platform=platform,
                video_path=video_path,
                title=title,
                description=description,
                **kwargs,
            )
            for platform in platforms
        }

        # Запускаем все загрузки параллельно
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        # Формируем словарь результатов
        return {
            platform: result if not isinstance(result, Exception) else None
            for platform, result in zip(platforms, results, strict=True)
        }

    async def batch_upload_to_platform(
        self, platform: str, video_files: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Пакетная загрузка видео на конкретную платформу."""

        results = []

        for video_info in video_files:
            video_path = video_info.get('path')
            title = video_info.get('title', 'Untitled')
            description = video_info.get('description', '')

            if not video_path:
                logger.error(f"❌ Не указан путь к видео: {video_info}")
                continue

            logger.info(f"📤 Загрузка {title} на {platform}...")

            kwargs = {
                k: v for k, v in video_info.items() if k not in ['path', 'title', 'description']
            }

            result = await self.upload_to_platform(
                platform=platform,
                video_path=video_path,
                title=title,
                description=description,
                **kwargs,
            )

            results.append(
                {
                    'video_path': video_path,
                    'title': title,
                    'platform': platform,
                    'result': result,
                    'upload_time': datetime.now().isoformat(),
                }
            )

        return results

    def get_upload_statistics(self, results: list[dict[str, Any]], platform: str) -> dict[str, Any]:
        """Получение статистики загрузки."""

        total_videos = len(results)
        successful_uploads = 0
        failed_uploads = 0

        for result in results:
            platform_result = result.get('result')
            if platform_result and platform_result.status == 'uploaded':
                successful_uploads += 1
            else:
                failed_uploads += 1

        success_rate = (successful_uploads / total_videos * 100) if total_videos > 0 else 0

        return {
            'platform': platform,
            'total_videos': total_videos,
            'successful_uploads': successful_uploads,
            'failed_uploads': failed_uploads,
            'success_rate': success_rate,
        }

    async def authenticate_all(self) -> dict[str, bool]:
        """Аутентификация на всех платформах."""
        results = {}

        for platform, uploader in self.uploaders.items():
            logger.info(f"🔐 Аутентификация на {platform}...")
            success = await uploader.authenticate()
            results[platform] = success

        return results

    async def authenticate_platforms(self, platforms: list[str]) -> dict[str, bool]:
        """Аутентификация только на указанных платформах."""
        results = {}

        for platform in platforms:
            if platform in self.uploaders:
                logger.info(f"🔐 Аутентификация на {platform}...")
                success = await self.uploaders[platform].authenticate()
                results[platform] = success
            else:
                logger.error(f"❌ Платформа {platform} не настроена")
                results[platform] = False

        return results

    async def close_all(self):
        """Закрытие всех соединений."""
        logger.info("🔌 Все соединения закрыты")
