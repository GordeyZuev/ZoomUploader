"""Base uploader classes and data structures."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class UploadResult:
    """Video upload result."""

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
    """Base uploader class for all platforms."""

    def __init__(self, config):
        self.config = config
        self._authenticated = False

    @abstractmethod
    async def authenticate(self) -> bool:
        """Authenticate with the platform."""

    def is_authenticated(self) -> bool:
        """Check authentication status."""
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
        """Upload video to platform."""

    @abstractmethod
    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Get video information."""

    @abstractmethod
    async def delete_video(self, video_id: str) -> bool:
        """Delete video from platform."""

    def validate_file(self, file_path: str) -> tuple[bool, str]:
        """Validate file before upload."""

        if not Path(file_path).exists():
            return False, "File does not exist"

        file_size_mb = Path(file_path).stat().st_size / (1024 * 1024)
        if file_size_mb > 5000:
            return False, f"File too large: {file_size_mb:.1f}MB"

        return True, "OK"

    def _create_result(
        self,
        video_id: str,
        video_url: str,
        title: str,
        platform: str,
        metadata: dict[str, Any] | None = None,
    ) -> UploadResult:
        """Create upload result."""
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
        Upload captions/subtitles (not implemented by default).
        Override in platform-specific uploaders that support this feature.
        """
        return False
