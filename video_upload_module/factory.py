"""Uploader factory with user-specific credentials from DB."""

import json
import tempfile
from pathlib import Path
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from api.helpers.config_helper import ConfigHelper
from logger import get_logger

from .config_factory import VKConfig, YouTubeConfig
from .platforms.vk.uploader import VKUploader
from .platforms.youtube.uploader import YouTubeUploader

logger = get_logger()


class UploaderFactory:
    """Create uploaders with user credentials from DB."""

    @staticmethod
    async def create_youtube_uploader(
        session: AsyncSession, user_id: int, credential_id: int | None = None
    ) -> YouTubeUploader:
        """
        Create YouTubeUploader for user.

        Args:
            session: Database session
            user_id: User ID
            credential_id: Specific credential ID (optional)

        Returns:
            Configured YouTubeUploader

        Raises:
            ValueError: If credentials not found
        """
        config_helper = ConfigHelper(session, user_id)

        if credential_id:
            creds = await config_helper.cred_service.get_credentials_by_id(credential_id)
        else:
            creds = await config_helper.get_youtube_credentials()

        temp_dir = Path(tempfile.gettempdir()) / f"youtube_creds_user_{user_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        client_secrets_file = temp_dir / "client_secrets.json"
        credentials_file = temp_dir / "credentials.json"

        if "client_secrets" in creds:
            with open(client_secrets_file, "w", encoding="utf-8") as f:
                json.dump(creds["client_secrets"], f, ensure_ascii=False, indent=2)

        if "token" in creds:
            with open(credentials_file, "w", encoding="utf-8") as f:
                json.dump(creds, f, ensure_ascii=False, indent=2)

        config = YouTubeConfig(
            client_secrets_file=str(client_secrets_file),
            credentials_file=str(credentials_file),
            scopes=creds.get("scopes", ["https://www.googleapis.com/auth/youtube.upload"]),
            playlist_id=creds.get("playlist_id"),
            default_privacy=creds.get("default_privacy", "unlisted"),
            default_category=creds.get("default_category", "22"),
        )

        logger.info(f"Created YouTubeUploader for user {user_id}")
        return YouTubeUploader(config)

    @staticmethod
    async def create_vk_uploader(session: AsyncSession, user_id: int, credential_id: int | None = None) -> VKUploader:
        """
        Create VKUploader for user.

        Args:
            session: Database session
            user_id: User ID
            credential_id: Specific credential ID (optional)

        Returns:
            Configured VKUploader

        Raises:
            ValueError: If credentials not found
        """
        config_helper = ConfigHelper(session, user_id)

        if credential_id:
            creds = await config_helper.cred_service.get_credentials_by_id(credential_id)
        else:
            creds = await config_helper.get_vk_credentials()

        config = VKConfig(
            access_token=creds["access_token"],
            group_id=creds.get("group_id"),
            album_id=creds.get("album_id"),
            app_id=creds.get("app_id", "54249533"),
            scope=creds.get("scope", "video,groups,wall"),
        )

        logger.info(f"Created VKUploader for user {user_id}")
        return VKUploader(config)

    @staticmethod
    async def create_uploader(
        session: AsyncSession, user_id: int, platform: Literal["youtube", "vk"], credential_id: int | None = None
    ) -> YouTubeUploader | VKUploader:
        """
        Universal method for creating uploader for any platform.

        Args:
            session: Database session
            user_id: User ID
            platform: Platform (youtube, vk)
            credential_id: Specific credential ID (optional)

        Returns:
            Configured uploader

        Raises:
            ValueError: If platform not supported or credentials not found
        """
        if platform == "youtube":
            return await UploaderFactory.create_youtube_uploader(session, user_id, credential_id)
        if platform == "vk":
            return await UploaderFactory.create_vk_uploader(session, user_id, credential_id)
        raise ValueError(f"Unsupported platform: {platform}")

    @staticmethod
    async def create_uploader_by_preset_id(
        session: AsyncSession, user_id: int, preset_id: int
    ) -> YouTubeUploader | VKUploader:
        """
        Create uploader from output preset.

        Args:
            session: Database session
            user_id: User ID
            preset_id: Output preset ID

        Returns:
            Configured uploader

        Raises:
            ValueError: If preset not found or credentials unavailable
        """
        from api.repositories.template_repos import OutputPresetRepository

        preset_repo = OutputPresetRepository(session)
        preset = await preset_repo.find_by_id(preset_id, user_id)

        if not preset:
            raise ValueError(f"Output preset {preset_id} not found for user {user_id}")

        if not preset.credential_id:
            raise ValueError(f"Output preset {preset_id} has no credential configured")

        platform_map = {
            "YOUTUBE": "youtube",
            "VK": "vk",
        }

        platform = platform_map.get(preset.platform.upper())
        if not platform:
            raise ValueError(f"Unsupported platform in preset: {preset.platform}")

        return await UploaderFactory.create_uploader(
            session=session, user_id=user_id, platform=platform, credential_id=preset.credential_id
        )
