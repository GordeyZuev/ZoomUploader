import os

import aiohttp

from logger import get_logger

from ...config_factory import VKConfig

logger = get_logger()


class VKThumbnailManager:
    """
    Менеджер для работы с миниатюрами видео в VK
    """

    def __init__(self, config: VKConfig):
        self.config = config
        self.base_url = "https://api.vk.com/method"

    def validate_thumbnail(self, thumbnail_path: str) -> tuple[bool, str]:
        """Валидация миниатюры"""
        if not os.path.exists(thumbnail_path):
            return False, f"Файл не найден: {thumbnail_path}"

        # Проверяем размер файла (максимум 5MB для VK)
        file_size = os.path.getsize(thumbnail_path)
        if file_size > 5 * 1024 * 1024:
            return False, f"Файл слишком большой: {file_size / 1024 / 1024:.1f}MB (максимум 5MB)"

        # Проверяем расширение
        file_ext = os.path.splitext(thumbnail_path)[1].lower().lstrip('.')
        if file_ext not in ['jpg', 'jpeg', 'png']:
            return False, f"Неподдерживаемый формат: {file_ext} (поддерживаются: jpg, jpeg, png)"

        return True, "OK"

    async def set_video_thumbnail(self, video_id: str, owner_id: str, thumbnail_path: str) -> bool:
        """Установка миниатюры для видео"""
        try:
            # Валидация
            is_valid, message = self.validate_thumbnail(thumbnail_path)
            if not is_valid:
                logger.error(f"❌ Миниатюра не прошла валидацию: {message}")
                return False

            # Получаем URL для загрузки миниатюры
            upload_url = await self._get_thumbnail_upload_url(owner_id)
            if not upload_url:
                logger.error("❌ Не удалось получить URL для загрузки миниатюры")
                return False

            # Загружаем миниатюру
            upload_result = await self._upload_thumbnail_file(upload_url, thumbnail_path)
            if not upload_result:
                logger.error("❌ Ошибка загрузки миниатюры")
                return False

            # Сохраняем миниатюру для видео
            success = await self._save_uploaded_thumbnail(video_id, owner_id, upload_result)
            if success:
                logger.info(f"🖼️ Миниатюра установлена для видео {video_id}")
                return True
            else:
                logger.error("❌ Ошибка сохранения миниатюры")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка установки миниатюры: {e}")
            return False

    async def _get_thumbnail_upload_url(self, owner_id: str) -> str | None:
        """Получение URL для загрузки миниатюры видео"""
        try:
            params = {'access_token': self.config.access_token, 'owner_id': owner_id, 'v': '5.199'}

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/video.getThumbUploadUrl", data=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'error' in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return None
                        return data['response']['upload_url']
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения URL загрузки миниатюры: {e}")
            return None

    async def _upload_thumbnail_file(self, upload_url: str, thumbnail_path: str) -> str | None:
        """Загрузка файла миниатюры на сервер"""
        try:
            with open(thumbnail_path, 'rb') as thumbnail_file:
                files = {'file': thumbnail_file}

                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=files) as response:
                        if response.status == 200:
                            text = await response.text()
                            logger.info("🖼️ Миниатюра загружена на сервер")
                            return text
                        else:
                            logger.error(f"❌ HTTP Upload Error: {response.status}")
                            return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки миниатюры: {e}")
            return None

    async def _save_uploaded_thumbnail(
        self, video_id: str, owner_id: str, upload_result: str
    ) -> bool:
        """Сохранение загруженной миниатюры для видео"""
        try:
            params = {
                'access_token': self.config.access_token,
                'owner_id': owner_id,
                'thumb_json': upload_result,  # Передаем текст ответа напрямую
                'v': '5.241',
                'video_id': video_id,
                'set_thumb': 1,  # Устанавливаем миниатюру
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/video.saveUploadedThumb", data=params
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'error' in data:
                            logger.error(
                                f"❌ VK API Error при сохранении миниатюры: {data['error']}"
                            )
                            return False

                        logger.info(f"🖼️ Миниатюра сохранена для видео {video_id}")
                        return True
                    else:
                        logger.error(f"❌ HTTP Error при сохранении миниатюры: {response.status}")
                        return False
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения миниатюры: {e}")
            return False
