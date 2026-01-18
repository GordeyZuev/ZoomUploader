"""YouTube thumbnail manager."""

import asyncio
from pathlib import Path
from typing import Any

import aiohttp
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from logger import get_logger

from ...config_factory import YouTubeConfig
from ...credentials_provider import CredentialProvider
from .token_handler import TokenRefreshError, requires_valid_token

logger = get_logger()


class YouTubeThumbnailManager:
    """YouTube thumbnail manager."""

    def __init__(
        self,
        service,
        config: YouTubeConfig,
        credentials=None,
        credential_provider: CredentialProvider | None = None,
    ):
        self.service = service
        self.config = config
        self.credentials = credentials
        self.credential_provider = credential_provider
        self.supported_formats = ["jpg", "jpeg", "png", "gif"]
        self.max_file_size = 2 * 1024 * 1024
        self.recommended_size = (1280, 720)

    def validate_thumbnail(self, thumbnail_path: str) -> tuple[bool, str]:
        """Validate thumbnail."""
        thumb_path = Path(thumbnail_path)
        if not thumb_path.exists():
            return False, "File does not exist"

        file_size = thumb_path.stat().st_size
        if file_size > self.max_file_size:
            return False, f"File too large: {file_size / 1024 / 1024:.1f}MB > 2MB"

        file_ext = thumb_path.suffix.lower().lstrip(".")
        if file_ext not in self.supported_formats:
            return (
                False,
                f"Unsupported format: {file_ext}. Supported: {', '.join(self.supported_formats)}",
            )

        return True, "OK"

    @requires_valid_token(max_retries=1)
    async def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        """Set thumbnail for video."""
        is_valid, message = self.validate_thumbnail(thumbnail_path)
        if not is_valid:
            logger.error(f"Thumbnail validation failed: {message}")
            return False

        try:
            media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
            self.service.thumbnails().set(videoId=video_id, media_body=media).execute()

            logger.info(f"Thumbnail set for video {video_id}")
            return True

        except TokenRefreshError as e:
            logger.error(f"Token error during set_thumbnail: {e}")
            return False
        except HttpError as e:
            logger.error(f"Thumbnail set error: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected thumbnail error: {e}")
            return False

    @requires_valid_token(max_retries=1)
    async def get_thumbnail_info(self, video_id: str) -> dict[str, Any] | None:
        """Get video thumbnail information."""
        try:
            request = self.service.videos().list(part="snippet", id=video_id)
            response = request.execute()

            if response["items"]:
                video = response["items"][0]
                thumbnails = video["snippet"].get("thumbnails", {})

                return {
                    "video_id": video_id,
                    "has_custom_thumbnail": "maxres" in thumbnails or "standard" in thumbnails,
                    "available_sizes": list(thumbnails.keys()),
                    "default_thumbnail": thumbnails.get("default", {}).get("url"),
                    "high_thumbnail": thumbnails.get("high", {}).get("url"),
                    "maxres_thumbnail": thumbnails.get("maxres", {}).get("url"),
                }

            return None

        except TokenRefreshError as e:
            logger.error(f"Token error during get_thumbnail_info: {e}")
            return None
        except HttpError as e:
            logger.error(f"Error getting thumbnail info: {e}")
            return None

    async def download_thumbnail(self, video_id: str, output_path: str, size: str = "maxres") -> bool:
        """Download video thumbnail."""
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
                logger.warning(f"Thumbnail size {size} not found")
                return False

            async with aiohttp.ClientSession() as session:
                async with session.get(thumbnail_url) as response:
                    if response.status == 200:
                        with open(output_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(8192):
                                f.write(chunk)

                        logger.info(f"Thumbnail downloaded: {output_path}")
                        return True
                    logger.error(f"Thumbnail download error: HTTP {response.status}")
                    return False

        except Exception as e:
            logger.error(f"Thumbnail download error: {e}")
            return False

    async def batch_set_thumbnails(self, video_thumbnail_pairs: list[tuple]) -> dict[str, bool]:
        """Batch set thumbnails."""
        results = {}

        for video_id, thumbnail_path in video_thumbnail_pairs:
            logger.info(f"Setting thumbnail for video {video_id}...")
            success = await self.set_thumbnail(video_id, thumbnail_path)
            results[video_id] = success

            await asyncio.sleep(1)

        return results

    def get_thumbnail_recommendations(self) -> dict[str, Any] | None:
        """Get thumbnail recommendations."""
        return {
            "recommended_size": f"{self.recommended_size[0]}x{self.recommended_size[1]}",
            "aspect_ratio": "16:9",
            "max_file_size_mb": self.max_file_size / (1024 * 1024),
            "supported_formats": self.supported_formats,
            "tips": [
                "Use bright, contrasting colors",
                "Add text with video title",
                "Avoid small details",
                "Check how thumbnail looks on mobile devices",
            ],
        }
