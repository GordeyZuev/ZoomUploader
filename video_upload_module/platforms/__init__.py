"""Platform-specific uploaders."""

from .vk import VKUploader
from .youtube import YouTubeUploader

__all__ = ["YouTubeUploader", "VKUploader"]
