"""Video upload module for YouTube and VK platforms."""

from .config_factory import (
    PlatformConfig,
    UploadConfig,
    UploadConfigFactory,
    VKConfig,
    YouTubeConfig,
)
from .core import BaseUploader, UploadManager, UploadResult
from .platforms import VKUploader, YouTubeUploader

__all__ = [
    # Core classes
    "BaseUploader",
    "UploadResult",
    "UploadManager",
    # Configuration
    "UploadConfig",
    "YouTubeConfig",
    "VKConfig",
    "PlatformConfig",
    "UploadConfigFactory",
    # Platform uploaders
    "YouTubeUploader",
    "VKUploader",
]
