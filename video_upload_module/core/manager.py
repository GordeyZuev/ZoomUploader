"""Universal upload manager for multiple platforms."""

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
    """Universal video upload manager for multiple platforms."""

    def __init__(self, config: UploadConfig):
        self.config = config
        self.uploaders: dict[str, BaseUploader] = {}
        self._initialize_uploaders()

    def _initialize_uploaders(self):
        """Initialize platform uploaders."""
        if self.config.youtube:
            self.uploaders["youtube"] = YouTubeUploader(self.config.youtube)
        if self.config.vk:
            self.uploaders["vk"] = VKUploader(self.config.vk)

    def add_uploader(self, platform: str, uploader: BaseUploader):
        """Add uploader for a platform."""
        self.uploaders[platform] = uploader

    def get_uploader(self, platform: str) -> BaseUploader | None:
        """Get uploader by platform name."""
        return self.uploaders.get(platform)

    def get_available_platforms(self) -> list[str]:
        """Get list of available platforms."""
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
        """Upload video to specific platform."""

        uploader = self.get_uploader(platform)
        if not uploader:
            logger.error(f"Uploader for platform {platform} not found")
            return None

        is_valid, message = uploader.validate_file(video_path)
        if not is_valid:
            logger.error(f"File validation failed: {message}")
            return None

        for attempt in range(self.config.retry_attempts):
            try:
                logger.info(f"Upload attempt {attempt + 1}/{self.config.retry_attempts} to {platform}")

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
                logger.error(f"Upload error to {platform} (attempt {attempt + 1}): {e}")

                if attempt < self.config.retry_attempts - 1:
                    logger.info(f"Waiting {self.config.retry_delay} seconds before retry...")
                    await asyncio.sleep(self.config.retry_delay)

        logger.error(f"Failed to upload video to {platform} after {self.config.retry_attempts} attempts")
        return None

    async def upload_caption(
        self,
        platform: str,
        video_id: str,
        caption_path: str,
        language: str = "ru",
        name: str | None = None,
    ) -> bool:
        """Upload captions if platform supports it."""
        uploader = self.get_uploader(platform)
        if not uploader:
            logger.error(f"Uploader for platform {platform} not found")
            return False

        if not hasattr(uploader, "upload_caption"):
            logger.info(f"Platform {platform} does not support caption upload")
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
            logger.error(f"Caption upload error to {platform}: {e}")
            return False

    async def upload_to_all_platforms(
        self, video_path: str, title: str, description: str = "", **kwargs
    ) -> dict[str, UploadResult | None]:
        """Upload video to all configured platforms (in parallel)."""

        platforms = self.get_available_platforms()
        if not platforms:
            return {}

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

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        return {
            platform: result if not isinstance(result, Exception) else None
            for platform, result in zip(platforms, results, strict=True)
        }

    async def batch_upload_to_platform(self, platform: str, video_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch upload videos to specific platform."""

        results = []

        for video_info in video_files:
            video_path = video_info.get("path")
            title = video_info.get("title", "Untitled")
            description = video_info.get("description", "")

            if not video_path:
                logger.error(f"Video path not specified: {video_info}")
                continue

            logger.info(f"Uploading {title} to {platform}...")

            kwargs = {k: v for k, v in video_info.items() if k not in ["path", "title", "description"]}

            result = await self.upload_to_platform(
                platform=platform,
                video_path=video_path,
                title=title,
                description=description,
                **kwargs,
            )

            results.append(
                {
                    "video_path": video_path,
                    "title": title,
                    "platform": platform,
                    "result": result,
                    "upload_time": datetime.now().isoformat(),
                }
            )

        return results

    def get_upload_statistics(self, results: list[dict[str, Any]], platform: str) -> dict[str, Any]:
        """Get upload statistics."""

        total_videos = len(results)
        successful_uploads = 0
        failed_uploads = 0

        for result in results:
            platform_result = result.get("result")
            if platform_result and platform_result.status == "uploaded":
                successful_uploads += 1
            else:
                failed_uploads += 1

        success_rate = (successful_uploads / total_videos * 100) if total_videos > 0 else 0

        return {
            "platform": platform,
            "total_videos": total_videos,
            "successful_uploads": successful_uploads,
            "failed_uploads": failed_uploads,
            "success_rate": success_rate,
        }

    async def authenticate_all(self) -> dict[str, bool]:
        """Authenticate on all platforms."""
        results = {}

        for platform, uploader in self.uploaders.items():
            logger.info(f"Authenticating on {platform}...")
            success = await uploader.authenticate()
            results[platform] = success

        return results

    async def authenticate_platforms(self, platforms: list[str]) -> dict[str, bool]:
        """Authenticate only on specified platforms."""
        results = {}

        for platform in platforms:
            if platform in self.uploaders:
                logger.info(f"Authenticating on {platform}...")
                success = await self.uploaders[platform].authenticate()
                results[platform] = success
            else:
                logger.error(f"Platform {platform} not configured")
                results[platform] = False

        return results

    async def close_all(self):
        """Close all connections."""
        logger.info("All connections closed")
