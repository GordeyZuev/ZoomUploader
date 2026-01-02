"""Factory для создания uploaders с user-specific credentials из БД.

Обеспечивает создание uploaders с правильными credentials
из базы данных для каждого пользователя.
"""

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
    """Factory для создания uploaders с credentials пользователя из БД."""

    @staticmethod
    async def create_youtube_uploader(
        session: AsyncSession,
        user_id: int,
        credential_id: int | None = None
    ) -> YouTubeUploader:
        """
        Создать YouTubeUploader для пользователя.

        Args:
            session: Database session
            user_id: ID пользователя
            credential_id: ID конкретного credential (опционально)

        Returns:
            Настроенный YouTubeUploader

        Raises:
            ValueError: Если credentials не найдены
        """
        config_helper = ConfigHelper(session, user_id)

        # Получаем YouTube credentials
        if credential_id:
            # Получаем по ID credential
            creds = await config_helper.cred_service.get_credentials_by_id(credential_id)
        else:
            # Получаем первые доступные YouTube credentials
            creds = await config_helper.get_youtube_credentials()

        # YouTube credentials хранятся как полный bundle (client_secrets + token)
        # Создаем временные файлы для совместимости с существующим API

        # Создаем временную директорию для credentials
        temp_dir = Path(tempfile.gettempdir()) / f"youtube_creds_user_{user_id}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Файл с client secrets
        client_secrets_file = temp_dir / "client_secrets.json"
        credentials_file = temp_dir / "credentials.json"

        # Сохраняем credentials во временные файлы
        # YouTube bundle должен содержать client_secrets и опционально token
        if "client_secrets" in creds:
            with open(client_secrets_file, "w", encoding="utf-8") as f:
                json.dump(creds["client_secrets"], f, ensure_ascii=False, indent=2)

        # Если есть token, сохраняем credentials file
        if "token" in creds:
            with open(credentials_file, "w", encoding="utf-8") as f:
                json.dump(creds, f, ensure_ascii=False, indent=2)

        # Создаем конфигурацию
        config = YouTubeConfig(
            client_secrets_file=str(client_secrets_file),
            credentials_file=str(credentials_file),
            scopes=creds.get("scopes", ["https://www.googleapis.com/auth/youtube.upload"]),
            # Другие параметры из creds
            playlist_id=creds.get("playlist_id"),
            default_privacy=creds.get("default_privacy", "unlisted"),
            default_category=creds.get("default_category", "22"),
        )

        logger.info(f"Created YouTubeUploader for user {user_id}")
        return YouTubeUploader(config)

    @staticmethod
    async def create_vk_uploader(
        session: AsyncSession,
        user_id: int,
        credential_id: int | None = None
    ) -> VKUploader:
        """
        Создать VKUploader для пользователя.

        Args:
            session: Database session
            user_id: ID пользователя
            credential_id: ID конкретного credential (опционально)

        Returns:
            Настроенный VKUploader

        Raises:
            ValueError: Если credentials не найдены
        """
        config_helper = ConfigHelper(session, user_id)

        # Получаем VK credentials
        if credential_id:
            creds = await config_helper.cred_service.get_credentials_by_id(credential_id)
        else:
            creds = await config_helper.get_vk_credentials()

        # Создаем конфигурацию
        config = VKConfig(
            access_token=creds["access_token"],
            group_id=creds.get("group_id"),
            album_id=creds.get("album_id"),
            # Другие параметры
            app_id=creds.get("app_id", "54249533"),
            scope=creds.get("scope", "video,groups,wall"),
        )

        logger.info(f"Created VKUploader for user {user_id}")
        return VKUploader(config)

    @staticmethod
    async def create_uploader(
        session: AsyncSession,
        user_id: int,
        platform: Literal["youtube", "vk"],
        credential_id: int | None = None
    ) -> YouTubeUploader | VKUploader:
        """
        Универсальный метод для создания uploader любой платформы.

        Args:
            session: Database session
            user_id: ID пользователя
            platform: Платформа (youtube, vk)
            credential_id: ID конкретного credential (опционально)

        Returns:
            Настроенный uploader

        Raises:
            ValueError: Если platform не поддерживается или credentials не найдены
        """
        if platform == "youtube":
            return await UploaderFactory.create_youtube_uploader(session, user_id, credential_id)
        elif platform == "vk":
            return await UploaderFactory.create_vk_uploader(session, user_id, credential_id)
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    @staticmethod
    async def create_uploader_by_preset_id(
        session: AsyncSession,
        user_id: int,
        preset_id: int
    ) -> YouTubeUploader | VKUploader:
        """
        Создать uploader из output preset.

        Args:
            session: Database session
            user_id: ID пользователя
            preset_id: ID output preset

        Returns:
            Настроенный uploader

        Raises:
            ValueError: Если preset не найден или credentials недоступны
        """
        from api.repositories.template_repos import OutputPresetRepository

        preset_repo = OutputPresetRepository(session)
        preset = await preset_repo.find_by_id(preset_id, user_id)

        if not preset:
            raise ValueError(f"Output preset {preset_id} not found for user {user_id}")

        if not preset.credential_id:
            raise ValueError(f"Output preset {preset_id} has no credential configured")

        # Определяем платформу по preset.platform
        platform_map = {
            "YOUTUBE": "youtube",
            "VK": "vk",
        }

        platform = platform_map.get(preset.platform.upper())
        if not platform:
            raise ValueError(f"Unsupported platform in preset: {preset.platform}")

        return await UploaderFactory.create_uploader(
            session=session,
            user_id=user_id,
            platform=platform,
            credential_id=preset.credential_id
        )

