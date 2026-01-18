"""Video upload configuration factory."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.unified_config import PlatformConfig, VKConfig, YouTubeConfig
from logger import get_logger

logger = get_logger()


class YouTubeUploadConfig(PlatformConfig):
    """YouTube API upload configuration."""

    client_secrets_file: str = Field(
        default="youtube_client_secrets.json",
        description="Path to client secrets file",
    )
    credentials_file: str = Field(
        default="youtube_credentials.json",
        description="Path to credentials file",
    )
    scopes: list[str] = Field(
        default_factory=lambda: [
            "https://www.googleapis.com/auth/youtube.upload",
            "https://www.googleapis.com/auth/youtube.force-ssl",
        ],
        description="YouTube API scopes",
    )
    default_privacy: Literal["private", "unlisted", "public"] = Field(
        default="unlisted",
        description="Default privacy setting",
    )
    default_language: str = Field(
        default="ru",
        description="Default language",
    )

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        """Validate YouTube API scopes."""
        if not v:
            logger.warning("No scopes specified for YouTube API")
        return v

    def validate(self) -> bool:
        """Validate configuration."""

        if not Path(self.client_secrets_file).exists():
            logger.warning(f"Client secrets file not found: {self.client_secrets_file}")

        if self.default_privacy not in ["private", "unlisted", "public"]:
            logger.error(f"Invalid privacy status: {self.default_privacy}")
            return False

        return True


class VKUploadConfig(PlatformConfig):
    """VK API upload configuration."""

    access_token: str = Field(
        default="",
        description="VK access token",
    )
    app_id: str = Field(
        default="54249533",
        description="VK application ID",
    )
    scope: str = Field(
        default="video,groups,wall",
        description="Access rights scope",
    )
    group_id: int | None = Field(
        default=None,
        description="VK group ID",
    )
    album_id: int | None = Field(
        default=None,
        description="VK album ID",
    )
    name: str = Field(
        default="",
        description="Name",
    )
    description: str = Field(
        default="",
        description="Description",
    )
    privacy_view: Literal["0", "1", "2"] = Field(
        default="0",
        description="View privacy settings",
    )
    privacy_comment: Literal["0", "1", "2"] = Field(
        default="1",
        description="Comment privacy settings",
    )
    no_comments: bool = Field(
        default=False,
        description="Disable comments",
    )
    repeat: bool = Field(
        default=False,
        description="Enable repeat",
    )

    def validate(self) -> bool:
        """Validate configuration."""
        if not self.access_token:
            logger.warning("VK access_token not specified")

        if not self.app_id:
            logger.warning("VK app_id not specified")

        if not self.scope:
            logger.warning("VK scope not specified")

        return True


class UploadConfig(BaseSettings):
    """Main upload system configuration."""

    model_config = SettingsConfigDict(
        extra="ignore",
        case_sensitive=False,
    )

    youtube: YouTubeUploadConfig | None = Field(
        default=None,
        description="YouTube configuration",
    )
    vk: VKUploadConfig | None = Field(
        default=None,
        description="VK configuration",
    )
    max_file_size_mb: int = Field(
        default=5000,
        ge=1,
        description="Maximum file size in MB",
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: ["mp4", "avi", "mov", "mkv", "webm", "m4v"],
        description="Supported file formats",
    )
    retry_attempts: int = Field(
        default=3,
        ge=1,
        description="Number of retry attempts on error",
    )
    retry_delay: int = Field(
        default=5,
        ge=0,
        description="Delay between retry attempts in seconds",
    )

    def validate(self) -> bool:
        """Validate entire configuration."""
        if self.youtube and not self.youtube.validate():
            return False

        return not (self.vk and not self.vk.validate())


class UploadConfigFactory:
    """Factory for creating upload configurations."""

    @staticmethod
    def from_app_config(app_config) -> UploadConfig:
        """
        Create upload configuration from unified app config.
        """
        youtube = None
        vk = None

        if "youtube" in app_config.platforms:
            youtube_platform = app_config.platforms["youtube"]
            if isinstance(youtube_platform, YouTubeConfig):
                youtube = YouTubeUploadConfig(
                    enabled=youtube_platform.enabled,
                    client_secrets_file=youtube_platform.client_secrets_file,
                    credentials_file=youtube_platform.credentials_file,
                    scopes=youtube_platform.scopes,
                    default_privacy=youtube_platform.default_privacy,
                    default_language=youtube_platform.default_language,
                )

        if "vk" in app_config.platforms:
            vk_platform = app_config.platforms["vk"]
            if isinstance(vk_platform, VKConfig):
                vk = VKUploadConfig(
                    enabled=vk_platform.enabled,
                    access_token=vk_platform.access_token,
                    app_id=getattr(vk_platform, "app_id", "54249533"),
                    scope=getattr(vk_platform, "scope", "video,groups,wall"),
                    group_id=vk_platform.group_id,
                    album_id=vk_platform.album_id,
                    name=vk_platform.name,
                    description=vk_platform.description,
                    privacy_view=vk_platform.privacy_view,
                    privacy_comment=vk_platform.privacy_comment,
                    no_comments=vk_platform.no_comments,
                    repeat=vk_platform.repeat,
                )

        upload_settings = app_config.upload_settings
        return UploadConfig(
            youtube=youtube,
            vk=vk,
            max_file_size_mb=upload_settings.max_file_size_mb,
            supported_formats=upload_settings.supported_formats,
            retry_attempts=upload_settings.retry_attempts,
            retry_delay=upload_settings.retry_delay,
        )
