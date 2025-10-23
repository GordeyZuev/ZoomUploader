"""
Основной загрузчик VK
"""

import asyncio
import os
from typing import Any

import aiohttp

from logger import get_logger

from ...config_factory import VKConfig
from ...core.base import BaseUploader, UploadResult

logger = get_logger()


class VKUploader(BaseUploader):
    """Загрузчик видео на VK."""

    def __init__(self, config: VKConfig):
        super().__init__(config)
        self.config = config
        self.base_url = "https://api.vk.com/method"
        self._authenticated = False

        self.logger = logger

    async def authenticate(self) -> bool:
        """Аутентификация в VK API."""
        if not self.config.access_token:
            self.logger.error("VK access_token не настроен")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                params = {'access_token': self.config.access_token, 'v': '5.131'}
                async with session.get(f"{self.base_url}/users.get", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'error' in data:
                            self.logger.error(f"VK API Error: {data['error']}")
                            return False
                        self._authenticated = True
                        self.logger.info("Аутентификация VK успешна")
                        return True
                    else:
                        self.logger.error(f"HTTP Error: {response.status}")
                        return False
        except Exception as e:
            self.logger.error(f"Ошибка аутентификации VK: {e}")
            return False

    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        album_id: str | None = None,
        thumbnail_path: str | None = None,
        progress=None,
        task_id=None,
        **kwargs,
    ) -> UploadResult | None:
        """Загрузка видео на VK."""

        if not self._authenticated:
            if not await self.authenticate():
                return None

        try:
            self.logger.info(f"Загрузка видео на VK: {title}")

            upload_url = await self._get_upload_url(title, description, album_id)
            if not upload_url:
                self.logger.error("Не удалось получить URL для загрузки")
                return None

            upload_result = await self._upload_video_file(upload_url, video_path, progress, task_id)
            if not upload_result:
                self.logger.error("Ошибка загрузки файла")
                return None

            video_id = upload_result.get('video_id')
            owner_id = upload_result.get('owner_id')

            if video_id and owner_id:
                video_url = f"https://vk.com/video{owner_id}_{video_id}"

                self.logger.info(f"Видео загружено: {video_url}")

                result = self._create_result(
                    video_id=video_id, video_url=video_url, title=title, platform="vk"
                )
                result.metadata['owner_id'] = owner_id

                # Устанавливаем миниатюру если есть
                if thumbnail_path and os.path.exists(thumbnail_path):
                    try:
                        from .thumbnail_manager import VKThumbnailManager

                        thumbnail_manager = VKThumbnailManager(self.config)
                        await asyncio.sleep(3)  # Небольшая задержка после загрузки видео
                        success = await thumbnail_manager.set_video_thumbnail(
                            video_id, owner_id, thumbnail_path
                        )
                        if success:
                            result.metadata['thumbnail_set'] = True
                            self.logger.info(f"🖼️ Миниатюра установлена для видео {video_id}")
                        else:
                            result.metadata['thumbnail_error'] = "Не удалось установить миниатюру"
                    except Exception as e:
                        self.logger.warning(f"Не удалось установить миниатюру: {e}")
                        result.metadata['thumbnail_error'] = str(e)

                return result
            else:
                self.logger.error("Не удалось получить ID видео после загрузки")
                return None

        except Exception as e:
            self.logger.error(f"Ошибка загрузки видео на VK: {e}")
            return None

    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Получение информации о видео."""
        if not self._authenticated:
            return None

        params = {
            'videos': video_id,  # Формат: owner_id_video_id
            'extended': 1,
        }

        response = await self._make_request('video.get', params)

        if response and 'items' in response and response['items']:
            video = response['items'][0]
            return {
                'title': video.get('title', ''),
                'description': video.get('description', ''),
                'duration': video.get('duration', 0),
                'views': video.get('views', 0),
                'date': video.get('date', 0),
                'privacy_view': video.get('privacy_view', 0),
                'privacy_comment': video.get('privacy_comment', 0),
            }

        return None

    async def delete_video(self, video_id: str) -> bool:
        """Удаление видео."""
        if not self._authenticated:
            return False

        params = {
            'video_id': video_id,
            'owner_id': None,  # Должен быть передан из метаданных
        }

        response = await self._make_request('video.delete', params)

        if response:
            self.logger.info(f"Видео удалено: {video_id}")
            return True
        else:
            self.logger.error(f"Ошибка удаления видео: {video_id}")
            return False

    async def _get_upload_url(
        self, name: str, description: str = "", album_id: str | None = None
    ) -> str:
        """Получение URL для загрузки видео."""
        params = {
            'name': name,
            'description': description,
            'privacy_view': self.config.privacy_view,
            'privacy_comment': self.config.privacy_comment,
            'no_comments': int(self.config.no_comments),
            'repeat': int(self.config.repeat),
        }

        if self.config.group_id:
            params['group_id'] = self.config.group_id

        target_album_id = album_id or self.config.album_id
        if target_album_id:
            params['album_id'] = target_album_id

        response = await self._make_request('video.save', params)

        if response and 'upload_url' in response:
            return response['upload_url']

        return None

    async def _upload_video_file(
        self, upload_url: str, video_path: str, progress=None, task_id=None
    ) -> dict[str, Any] | None:
        """Загрузка файла видео."""
        try:
            # Получаем размер файла для прогресс-бара
            os.path.getsize(video_path)

            with open(video_path, 'rb') as video_file:
                files = {'video_file': video_file}

                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=files) as response:
                        if response.status == 200:
                            data = await response.json()
                            if 'error' in data:
                                self.logger.error(f"VK Upload Error: {data['error']}")
                                return None

                            # Обновляем прогресс-бар до 100%
                            if progress and task_id is not None:
                                try:
                                    if task_id in progress.task_ids:
                                        progress.update(task_id, completed=100, total=100)
                                except Exception:
                                    pass  # Игнорируем ошибки обновления прогресса

                            return data
                        else:
                            self.logger.error(f"HTTP Upload Error: {response.status}")
                            return None
        except Exception as e:
            self.logger.error(f"Ошибка загрузки файла: {e}")
            return None

    async def _make_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Выполнение запроса к VK API."""
        params['access_token'] = self.config.access_token
        params['v'] = '5.131'

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/{method}", params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'error' in data:
                            self.logger.error(f"VK API Error: {data['error']}")
                            return None
                        return data.get('response')
                    else:
                        self.logger.error(f"HTTP Error: {response.status}")
                        return None
        except Exception as e:
            self.logger.error(f"Ошибка запроса к VK API: {e}")
            return None
