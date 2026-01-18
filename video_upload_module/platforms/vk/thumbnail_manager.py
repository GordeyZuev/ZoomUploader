"""VK video thumbnail manager."""

from pathlib import Path

import aiohttp

from logger import get_logger

from ...config_factory import VKConfig

logger = get_logger()


class VKThumbnailManager:
    """VK video thumbnail manager."""

    def __init__(self, config: VKConfig):
        self.config = config
        self.base_url = "https://api.vk.com/method"

    def validate_thumbnail(self, thumbnail_path: str) -> tuple[bool, str]:
        """Validate thumbnail."""
        thumb_path = Path(thumbnail_path)
        if not thumb_path.exists():
            return False, f"File not found: {thumbnail_path}"

        file_size = thumb_path.stat().st_size
        if file_size > 5 * 1024 * 1024:
            return False, f"File too large: {file_size / 1024 / 1024:.1f}MB (max 5MB)"

        file_ext = thumb_path.suffix.lower().lstrip(".")
        if file_ext not in ["jpg", "jpeg", "png"]:
            return False, f"Unsupported format: {file_ext} (supported: jpg, jpeg, png)"

        return True, "OK"

    async def set_video_thumbnail(self, video_id: str, owner_id: str, thumbnail_path: str) -> bool:
        """Set video thumbnail."""
        try:
            is_valid, message = self.validate_thumbnail(thumbnail_path)
            if not is_valid:
                logger.error(f"Thumbnail validation failed: {message}")
                return False

            upload_url = await self._get_thumbnail_upload_url(owner_id)
            if not upload_url:
                logger.error("Failed to get thumbnail upload URL")
                return False

            upload_result = await self._upload_thumbnail_file(upload_url, thumbnail_path)
            if not upload_result:
                logger.error("Thumbnail upload error")
                return False

            success = await self._save_uploaded_thumbnail(video_id, owner_id, upload_result)
            if success:
                logger.info(f"Thumbnail set for video {video_id}")
                return True
            logger.error("Thumbnail save error")
            return False

        except Exception as e:
            logger.error(f"Thumbnail set error: {e}")
            return False

    async def _get_thumbnail_upload_url(self, owner_id: str) -> str | None:
        """Get video thumbnail upload URL."""
        try:
            params = {"access_token": self.config.access_token, "owner_id": owner_id, "v": "5.199"}

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.getThumbUploadUrl", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"VK API Error: {data['error']}")
                            return None
                        return data["response"]["upload_url"]
                    logger.error(f"HTTP Error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting thumbnail upload URL: {e}")
            return None

    async def _upload_thumbnail_file(self, upload_url: str, thumbnail_path: str) -> str | None:
        """Upload thumbnail file to server."""
        try:
            with open(thumbnail_path, "rb") as thumbnail_file:
                files = {"file": thumbnail_file}

                async with aiohttp.ClientSession() as session:
                    async with session.post(upload_url, data=files) as response:
                        if response.status == 200:
                            text = await response.text()
                            logger.info("Thumbnail uploaded to server")
                            return text
                        logger.error(f"HTTP Upload Error: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Thumbnail upload error: {e}")
            return None

    async def _save_uploaded_thumbnail(self, video_id: str, owner_id: str, upload_result: str) -> bool:
        """Save uploaded thumbnail for video."""
        try:
            params = {
                "access_token": self.config.access_token,
                "owner_id": owner_id,
                "thumb_json": upload_result,
                "v": "5.241",
                "video_id": video_id,
                "set_thumb": 1,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(f"{self.base_url}/video.saveUploadedThumb", data=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" in data:
                            logger.error(f"VK API Error saving thumbnail: {data['error']}")
                            return False

                        logger.info(f"Thumbnail saved for video {video_id}")
                        return True
                    logger.error(f"HTTP Error saving thumbnail: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Thumbnail save error: {e}")
            return False
