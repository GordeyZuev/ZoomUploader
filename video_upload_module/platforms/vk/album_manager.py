from typing import Any

import aiohttp

from logger import get_logger

from ...config_factory import VKConfig

logger = get_logger()


class VKAlbumManager:
    """Менеджер для работы с альбомами VK"""

    def __init__(self, config: VKConfig):
        self.config = config
        self.base_url = "https://api.vk.com/method"

    async def create_album(self, title: str, description: str = "", privacy: int = 0) -> str | None:
        """Создание альбома для видео"""
        try:
            params = {
                "title": title,
                "description": description,
                "privacy": privacy,
                "access_token": self.config.access_token,
                "v": "5.131",
            }

            if self.config.group_id:
                params["group_id"] = self.config.group_id

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.addAlbum", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return None

                        album_id = data["response"]["album_id"]
                        logger.info(f"📁 Альбом создан: {album_id}")
                        return str(album_id)
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"❌ Ошибка создания альбома: {e}")
            return None

    async def get_albums(self, count: int = 100) -> list[dict[str, Any]]:
        """Получение списка альбомов"""
        try:
            params = {"count": count, "access_token": self.config.access_token, "v": "5.131"}

            if self.config.group_id:
                params["owner_id"] = -self.config.group_id

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.getAlbums", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return []

                        albums = []
                        for album in data["response"]["items"]:
                            albums.append(
                                {
                                    "album_id": album["id"],
                                    "title": album["title"],
                                    "description": album.get("description", ""),
                                    "count": album["count"],
                                    "updated_time": album["updated_time"],
                                }
                            )

                        logger.info(f"📁 Получено альбомов: {len(albums)}")
                        return albums
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return []

        except Exception as e:
            logger.error(f"❌ Ошибка получения альбомов: {e}")
            return []

    async def get_album_videos(self, album_id: str, count: int = 200) -> list[dict[str, Any]]:
        """Получение видео из альбома"""
        try:
            params = {
                "album_id": album_id,
                "count": count,
                "access_token": self.config.access_token,
                "v": "5.131",
            }

            if self.config.group_id:
                params["owner_id"] = -self.config.group_id

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.get", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return []

                        videos = []
                        for video in data["response"]["items"]:
                            videos.append(
                                {
                                    "video_id": video["id"],
                                    "owner_id": video["owner_id"],
                                    "title": video["title"],
                                    "description": video.get("description", ""),
                                    "duration": video.get("duration", 0),
                                    "views": video.get("views", 0),
                                    "date": video["date"],
                                }
                            )

                        logger.info(f"🎥 Получено видео из альбома: {len(videos)}")
                        return videos
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return []

        except Exception as e:
            logger.error(f"❌ Ошибка получения видео альбома: {e}")
            return []

    async def edit_album(
        self,
        album_id: str,
        title: str | None = None,
        description: str | None = None,
        privacy: int | None = None,
    ) -> bool:
        """Редактирование альбома"""
        try:
            params = {"album_id": album_id, "access_token": self.config.access_token, "v": "5.131"}

            if title:
                params["title"] = title
            if description:
                params["description"] = description
            if privacy is not None:
                params["privacy"] = privacy

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.editAlbum", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return False

                        logger.info(f"📁 Альбом отредактирован: {album_id}")
                        return True
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"❌ Ошибка редактирования альбома: {e}")
            return False

    async def delete_album(self, album_id: str) -> bool:
        """Удаление альбома"""
        try:
            params = {"album_id": album_id, "access_token": self.config.access_token, "v": "5.131"}

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.deleteAlbum", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return False

                        logger.info(f"📁 Альбом удален: {album_id}")
                        return True
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"❌ Ошибка удаления альбома: {e}")
            return False

    async def move_video_to_album(self, video_id: str, album_id: str, owner_id: str) -> bool:
        """Перемещение видео в альбом"""
        try:
            params = {
                "video_id": video_id,
                "owner_id": owner_id,
                "album_id": album_id,
                "access_token": self.config.access_token,
                "v": "5.131",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.moveToAlbum", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"❌ VK API Error: {data['error']}")
                            return False

                        logger.info(f"🎥 Видео перемещено в альбом: {album_id}")
                        return True
                    else:
                        logger.error(f"❌ HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"❌ Ошибка перемещения видео: {e}")
            return False
