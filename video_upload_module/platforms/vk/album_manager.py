"""VK album manager."""

from typing import Any

import aiohttp

from logger import get_logger

from ...config_factory import VKConfig

logger = get_logger()


class VKAlbumManager:
    """VK album manager."""

    def __init__(self, config: VKConfig):
        self.config = config
        self.base_url = "https://api.vk.com/method"

    async def create_album(self, title: str, description: str = "", privacy: int = 0) -> str | None:
        """Create video album."""
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
                            logger.error(f"VK API Error: {data['error']}")
                            return None

                        album_id = data["response"]["album_id"]
                        logger.info(f"Album created: {album_id}")
                        return str(album_id)
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return None

        except Exception as e:
            logger.error(f"Album creation error: {e}")
            return None

    async def get_albums(self, count: int = 100) -> list[dict[str, Any]]:
        """Get list of albums."""
        try:
            params = {"count": count, "access_token": self.config.access_token, "v": "5.131"}

            if self.config.group_id:
                params["owner_id"] = -self.config.group_id

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.getAlbums", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"VK API Error: {data['error']}")
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

                        logger.info(f"Albums retrieved: {len(albums)}")
                        return albums
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return []

        except Exception as e:
            logger.error(f"Error getting albums: {e}")
            return []

    async def get_album_videos(self, album_id: str, count: int = 200) -> list[dict[str, Any]]:
        """Get videos from album."""
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
                            logger.error(f"VK API Error: {data['error']}")
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

                        logger.info(f"Videos retrieved from album: {len(videos)}")
                        return videos
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return []

        except Exception as e:
            logger.error(f"Error getting album videos: {e}")
            return []

    async def edit_album(
        self,
        album_id: str,
        title: str | None = None,
        description: str | None = None,
        privacy: int | None = None,
    ) -> bool:
        """Edit album."""
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
                            logger.error(f"VK API Error: {data['error']}")
                            return False

                        logger.info(f"Album edited: {album_id}")
                        return True
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Album edit error: {e}")
            return False

    async def delete_album(self, album_id: str) -> bool:
        """Delete album."""
        try:
            params = {"album_id": album_id, "access_token": self.config.access_token, "v": "5.131"}

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.deleteAlbum", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"VK API Error: {data['error']}")
                            return False

                        logger.info(f"Album deleted: {album_id}")
                        return True
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Album deletion error: {e}")
            return False

    async def move_video_to_album(self, video_id: str, album_id: str, owner_id: str) -> bool:
        """Move video to album."""
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
                            logger.error(f"VK API Error: {data['error']}")
                            return False

                        logger.info(f"Video moved to album: {album_id}")
                        return True
                    else:
                        logger.error(f"HTTP Error: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Video move error: {e}")
            return False
