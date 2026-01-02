"""Сервис для работы с учетными данными пользователей.

Обеспечивает удобный интерфейс для получения расшифрованных credentials
и их использования в API запросах к внешним сервисам.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.encryption import get_encryption
from api.repositories.auth_repos import UserCredentialRepository
from logger import get_logger

logger = get_logger()


class CredentialService:
    """Сервис для работы с учетными данными."""

    def __init__(self, session: AsyncSession):
        """
        Инициализация сервиса.

        Args:
            session: Async database session
        """
        self.session = session
        self.repo = UserCredentialRepository(session)
        self.encryption = get_encryption()

    async def get_decrypted_credentials(
        self,
        user_id: int,
        platform: str,
        account_name: str | None = None,
        raise_if_not_found: bool = True
    ) -> dict[str, Any] | None:
        """
        Получить расшифрованные учетные данные для платформы.

        Args:
            user_id: ID пользователя
            platform: Платформа (zoom, youtube, vk, etc)
            account_name: Имя аккаунта (для множественных аккаунтов на одной платформе)
            raise_if_not_found: Выбрасывать ошибку если не найдено

        Returns:
            Расшифрованные учетные данные или None

        Raises:
            ValueError: Если credentials не найдены (при raise_if_not_found=True)
        """
        credential = await self.repo.get_by_platform(user_id, platform, account_name)

        if not credential:
            account_str = f" (account: {account_name})" if account_name else ""
            if raise_if_not_found:
                raise ValueError(f"Credentials for platform '{platform}'{account_str} not found for user {user_id}")
            return None

        if not credential.is_active:
            account_str = f" (account: {account_name})" if account_name else ""
            logger.warning(f"Credentials for platform '{platform}'{account_str} are inactive for user {user_id}")
            if raise_if_not_found:
                raise ValueError(f"Credentials for platform '{platform}'{account_str} are inactive")
            return None

        try:
            decrypted = self.encryption.decrypt_credentials(credential.encrypted_data)
            account_str = f" (account: {account_name})" if account_name else ""
            logger.debug(f"Successfully decrypted credentials for platform '{platform}'{account_str} for user {user_id}")
            return decrypted
        except Exception as e:
            logger.error(f"Failed to decrypt credentials for platform '{platform}': {e}")
            raise ValueError(f"Failed to decrypt credentials: {e}") from e

    async def get_zoom_credentials(
        self,
        user_id: int,
        account_name: str | None = None
    ) -> dict[str, str]:
        """
        Получить учетные данные Zoom.

        Args:
            user_id: ID пользователя
            account_name: Имя аккаунта (опционально, для множественных аккаунтов)

        Returns:
            Словарь с account_id, client_id, client_secret

        Raises:
            ValueError: Если credentials не найдены или невалидны
        """
        creds = await self.get_decrypted_credentials(user_id, "zoom", account_name)
        if not creds:
            raise ValueError("Zoom credentials not found")

        # Валидация структуры
        required_fields = ["account_id", "client_id", "client_secret"]
        missing = [f for f in required_fields if f not in creds]
        if missing:
            raise ValueError(f"Zoom credentials missing required fields: {missing}")

        return creds

    async def get_credentials_by_id(self, credential_id: int) -> dict[str, Any]:
        """
        Получить расшифрованные учетные данные по ID.

        Args:
            credential_id: ID credential

        Returns:
            Расшифрованные учетные данные

        Raises:
            ValueError: Если credentials не найдены или невалидны
        """
        credential = await self.repo.get_by_id(credential_id)

        if not credential:
            raise ValueError(f"Credential {credential_id} not found")

        if not credential.is_active:
            raise ValueError(f"Credential {credential_id} is inactive")

        try:
            decrypted = self.encryption.decrypt_credentials(credential.encrypted_data)
            logger.debug(f"Successfully decrypted credential {credential_id} (platform: {credential.platform})")
            return decrypted
        except Exception as e:
            logger.error(f"Failed to decrypt credential {credential_id}: {e}")
            raise ValueError(f"Failed to decrypt credential: {e}") from e

    async def get_youtube_credentials(self, user_id: int) -> dict[str, Any]:
        """
        Получить учетные данные YouTube (OAuth bundle).

        Args:
            user_id: ID пользователя

        Returns:
            Полный OAuth bundle (client_secrets, token, scopes)

        Raises:
            ValueError: Если credentials не найдены или невалидны
        """
        creds = await self.get_decrypted_credentials(user_id, "youtube")
        if not creds:
            raise ValueError("YouTube credentials not found")

        # YouTube хранит весь bundle как есть
        # Проверяем наличие client_secrets или token
        if "client_secrets" not in creds and "token" not in creds:
            raise ValueError("YouTube credentials missing client_secrets or token")

        return creds

    async def get_vk_credentials(self, user_id: int) -> dict[str, Any]:
        """
        Получить учетные данные VK.

        Args:
            user_id: ID пользователя

        Returns:
            Словарь с access_token и опционально group_id

        Raises:
            ValueError: Если credentials не найдены или невалидны
        """
        creds = await self.get_decrypted_credentials(user_id, "vk")
        if not creds:
            raise ValueError("VK credentials not found")

        if "access_token" not in creds:
            raise ValueError("VK credentials missing access_token")

        return creds

    async def get_api_key_credentials(self, user_id: int, platform: str) -> str:
        """
        Получить API ключ для сервисов (fireworks, deepseek, openai).

        Args:
            user_id: ID пользователя
            platform: Платформа (fireworks, deepseek, openai)

        Returns:
            API ключ

        Raises:
            ValueError: Если credentials не найдены или невалидны
        """
        creds = await self.get_decrypted_credentials(user_id, platform)
        if not creds:
            raise ValueError(f"{platform} credentials not found")

        api_key = creds.get("api_key")
        if not api_key:
            raise ValueError(f"{platform} credentials missing api_key")

        return api_key

    async def validate_credentials(self, user_id: int, platform: str) -> bool:
        """
        Проверить существование и валидность credentials.

        Args:
            user_id: ID пользователя
            platform: Платформа

        Returns:
            True если credentials валидны
        """
        try:
            await self.get_decrypted_credentials(user_id, platform, raise_if_not_found=True)
            return True
        except ValueError:
            return False

    async def list_available_platforms(self, user_id: int) -> list[str]:
        """
        Получить список доступных платформ для пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Список названий платформ
        """
        credentials = await self.repo.find_by_user(user_id)
        return [cred.platform for cred in credentials if cred.is_active]

    async def update_last_used(self, user_id: int, platform: str) -> None:
        """
        Обновить время последнего использования credentials.

        Args:
            user_id: ID пользователя
            platform: Платформа
        """
        credential = await self.repo.get_by_platform(user_id, platform)
        if credential:
            await self.repo.update_last_used(credential.id)
            logger.debug(f"Updated last_used_at for platform '{platform}' for user {user_id}")

