import asyncio
import os
from typing import Any

import aiohttp
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from logger import get_logger

from ...config_factory import YouTubeConfig

logger = get_logger()


class YouTubeThumbnailManager:
    """Менеджер для работы с миниатюрами YouTube"""

    def __init__(self, service, config: YouTubeConfig):
        self.service = service
        self.config = config
        self.supported_formats = ["jpg", "jpeg", "png", "gif"]
        self.max_file_size = 2 * 1024 * 1024  # 2MB
        self.recommended_size = (1280, 720)  # 16:9

    def validate_thumbnail(self, thumbnail_path: str) -> tuple[bool, str]:
        """Валидация миниатюры"""
        if not os.path.exists(thumbnail_path):
            return False, "Файл не существует"

        file_size = os.path.getsize(thumbnail_path)
        if file_size > self.max_file_size:
            return False, f"Файл слишком большой: {file_size / 1024 / 1024:.1f}MB > 2MB"

        file_ext = os.path.splitext(thumbnail_path)[1].lower().lstrip(".")
        if file_ext not in self.supported_formats:
            return (
                False,
                f"Неподдерживаемый формат: {file_ext}. Поддерживаются: {', '.join(self.supported_formats)}",
            )

        return True, "OK"

    async def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Установка миниатюры для видео"""
        # Валидация
        is_valid, message = self.validate_thumbnail(thumbnail_path)
        if not is_valid:
            logger.error(f"❌ Миниатюра не прошла валидацию: {message}")
            return False

        try:
            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            self.service.thumbnails().set(videoId=video_id, media_body=media).execute()

            logger.info(f"🖼️ Миниатюра установлена для видео {video_id}")
            return True

        except HttpError as e:
            logger.error(f"❌ Ошибка установки миниатюры: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при установке миниатюры: {e}")
            return False

    async def get_thumbnail_info(self, video_id: str) -> dict[str, Any] | None:
        """Получение информации о миниатюре видео"""
        try:
            request = self.service.videos().list(part="snippet", id=video_id)
            response = request.execute()

            if response["items"]:
                video = response["items"][0]
                thumbnails = video["snippet"].get("thumbnails", {})

                # Возвращаем информацию о доступных миниатюрах
                return {
                    "video_id": video_id,
                    "has_custom_thumbnail": "maxres" in thumbnails or "standard" in thumbnails,
                    "available_sizes": list(thumbnails.keys()),
                    "default_thumbnail": thumbnails.get("default", {}).get("url"),
                    "high_thumbnail": thumbnails.get("high", {}).get("url"),
                    "maxres_thumbnail": thumbnails.get("maxres", {}).get("url"),
                }

            return None

        except HttpError as e:
            logger.error(f"❌ Ошибка получения информации о миниатюре: {e}")
            return None

    async def download_thumbnail(self, video_id: str, output_path: str, size: str = "maxres") -> bool:
        """Скачивание миниатюры видео"""
        try:
            thumbnail_info = await self.get_thumbnail_info(video_id)
            if not thumbnail_info:
                return False

            # Выбираем размер миниатюры
            thumbnail_url = None
            if size in thumbnail_info.get("available_sizes", []):
                thumbnail_url = thumbnail_info.get(f"{size}_thumbnail")
            elif "high_thumbnail" in thumbnail_info:
                thumbnail_url = thumbnail_info["high_thumbnail"]
            elif "default_thumbnail" in thumbnail_info:
                thumbnail_url = thumbnail_info["default_thumbnail"]

            if not thumbnail_url:
                logger.warning(f"❌ Миниатюра размера {size} не найдена")
                return False

            # Скачиваем миниатюру
            async with aiohttp.ClientSession() as session:
                async with session.get(thumbnail_url) as response:
                    if response.status == 200:
                        with open(output_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)

                        logger.info(f"🖼️ Миниатюра скачана: {output_path}")
                        return True
                    else:
                        logger.error(f"❌ Ошибка скачивания миниатюры: HTTP {response.status}")
                        return False

        except Exception as e:
            logger.error(f"❌ Ошибка скачивания миниатюры: {e}")
            return False

    async def batch_set_thumbnails(self, video_thumbnail_pairs: list[tuple]) -> dict[str, bool]:
        """Пакетная установка миниатюр"""
        results = {}

        for video_id, thumbnail_path in video_thumbnail_pairs:
            logger.info(f"🖼️ Установка миниатюры для видео {video_id}...")
            success = await self.set_thumbnail(video_id, thumbnail_path)
            results[video_id] = success

            # Небольшая пауза между запросами
            await asyncio.sleep(1)

        return results

    def get_thumbnail_recommendations(self) -> dict[str, Any] | None:
        """Получение рекомендаций по миниатюрам"""
        return {
            "recommended_size": f"{self.recommended_size[0]}x{self.recommended_size[1]}",
            "aspect_ratio": "16:9",
            "max_file_size_mb": self.max_file_size / (1024 * 1024),
            "supported_formats": self.supported_formats,
            "tips": [
                "Используйте яркие, контрастные цвета",
                "Добавьте текст с названием видео",
                "Избегайте мелких деталей",
                "Проверьте как миниатюра выглядит на мобильных устройствах",
            ],
        }
