"""Helper for user configurations and credentials"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.services.credential_service import CredentialService
from config.settings import ZoomConfig
from deepseek_module import DeepSeekConfig
from fireworks_module import FireworksConfig
from logger import get_logger

logger = get_logger()


class ConfigHelper:
    """User configuration and credentials helper"""

    def __init__(self, session: AsyncSession, user_id: int):
        """
        Инициализация helper.

        Args:
            session: Database session
            user_id: ID пользователя
        """
        self.session = session
        self.user_id = user_id
        self.cred_service = CredentialService(session)

    async def get_zoom_config(self, account_name: str | None = None) -> ZoomConfig:
        """
        Получить ZoomConfig для пользователя.

        Args:
            account_name: Имя аккаунта (опционально)

        Returns:
            ZoomConfig с credentials пользователя

        Raises:
            ValueError: Если credentials не найдены
        """
        creds = await self.cred_service.get_zoom_credentials(
            user_id=self.user_id,
            account_name=account_name
        )

        return ZoomConfig(
            account=creds.get("account", ""),
            account_id=creds["account_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )

    async def get_zoom_config_by_credential_id(self, credential_id: int) -> ZoomConfig:
        """
        Получить ZoomConfig по ID credential.

        Args:
            credential_id: ID credential

        Returns:
            ZoomConfig с credentials

        Raises:
            ValueError: Если credentials не найдены
        """
        creds = await self.cred_service.get_credentials_by_id(credential_id)

        # Validate it's actually zoom credentials
        if "account_id" not in creds or "client_id" not in creds:
            raise ValueError(f"Credential {credential_id} is not valid Zoom credentials")

        return ZoomConfig(
            account=creds.get("account", ""),
            account_id=creds["account_id"],
            client_id=creds["client_id"],
            client_secret=creds["client_secret"],
        )

    async def get_fireworks_config(self) -> FireworksConfig:
        """
        Получить FireworksConfig для пользователя.

        Returns:
            FireworksConfig с API key пользователя

        Raises:
            ValueError: Если credentials не найдены
        """
        api_key = await self.cred_service.get_api_key_credentials(
            user_id=self.user_id,
            platform="fireworks"
        )

        # Используем конфигурацию по умолчанию, но с пользовательским API key
        config = FireworksConfig.from_file()
        config.api_key = api_key

        logger.debug(f"Retrieved Fireworks config for user {self.user_id}")
        return config

    async def get_deepseek_config(self) -> DeepSeekConfig:
        """
        Получить DeepSeekConfig для пользователя.

        Returns:
            DeepSeekConfig с API key пользователя

        Raises:
            ValueError: Если credentials не найдены
        """
        api_key = await self.cred_service.get_api_key_credentials(
            user_id=self.user_id,
            platform="deepseek"
        )

        # Используем конфигурацию по умолчанию, но с пользовательским API key
        config = DeepSeekConfig.from_file()
        config.api_key = api_key

        logger.debug(f"Retrieved DeepSeek config for user {self.user_id}")
        return config

    async def get_youtube_credentials(self) -> dict[str, Any]:
        """
        Получить YouTube credentials для пользователя.

        Returns:
            YouTube OAuth bundle

        Raises:
            ValueError: Если credentials не найдены
        """
        return await self.cred_service.get_youtube_credentials(self.user_id)

    async def get_vk_credentials(self) -> dict[str, Any]:
        """
        Получить VK credentials для пользователя.

        Returns:
            VK credentials (access_token, group_id)

        Raises:
            ValueError: Если credentials не найдены
        """
        return await self.cred_service.get_vk_credentials(self.user_id)

    async def get_credentials_for_platform(
        self,
        platform: str,
        account_name: str | None = None
    ) -> dict[str, Any]:
        """
        Универсальный метод для получения credentials любой платформы.

        Args:
            platform: Название платформы (zoom, youtube, vk, etc)
            account_name: Имя аккаунта (опционально)

        Returns:
            Расшифрованные credentials

        Raises:
            ValueError: Если credentials не найдены
        """
        return await self.cred_service.get_decrypted_credentials(
            user_id=self.user_id,
            platform=platform,
            account_name=account_name
        )

    async def has_credentials_for_platform(self, platform: str) -> bool:
        """
        Проверить наличие credentials для платформы.

        Args:
            platform: Название платформы

        Returns:
            True если credentials существуют и активны
        """
        return await self.cred_service.validate_credentials(self.user_id, platform)

    async def list_available_platforms(self) -> list[str]:
        """
        Получить список доступных платформ для пользователя.

        Returns:
            Список названий платформ
        """
        return await self.cred_service.list_available_platforms(self.user_id)
