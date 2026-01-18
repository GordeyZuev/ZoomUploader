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
    "PlatformConfig",
    # Configuration
    "UploadConfig",
    "UploadConfigFactory",
    "UploadManager",
    "UploadResult",
    "VKConfig",
    "VKUploader",
    "YouTubeConfig",
    # Platform uploaders
    "YouTubeUploader",
]
