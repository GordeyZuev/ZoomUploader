"""Factory для создания TranscriptionService с user-specific credentials.

Обеспечивает создание сервиса транскрипции с правильными credentials
из базы данных для каждого пользователя.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from api.helpers.config_helper import ConfigHelper
from logger import get_logger

from .service import TranscriptionService

logger = get_logger()


class TranscriptionServiceFactory:
    """Factory для создания TranscriptionService с credentials пользователя."""

    @staticmethod
    async def create_for_user(
        session: AsyncSession,
        user_id: int
    ) -> TranscriptionService:
        """
        Создать TranscriptionService для пользователя.

        Args:
            session: Database session
            user_id: ID пользователя

        Returns:
            Настроенный TranscriptionService с credentials пользователя

        Raises:
            ValueError: Если необходимые credentials не найдены
        """
        config_helper = ConfigHelper(session, user_id)

        # Проверяем наличие необходимых credentials
        has_deepseek = await config_helper.has_credentials_for_platform("deepseek")
        has_fireworks = await config_helper.has_credentials_for_platform("fireworks")

        if not has_deepseek:
            raise ValueError(
                f"DeepSeek credentials not found for user {user_id}. "
                "Please add DeepSeek API key to continue."
            )

        if not has_fireworks:
            raise ValueError(
                f"Fireworks credentials not found for user {user_id}. "
                "Please add Fireworks API key to continue."
            )

        # Получаем конфигурации
        deepseek_config = await config_helper.get_deepseek_config()
        fireworks_config = await config_helper.get_fireworks_config()

        logger.info(f"Created TranscriptionService for user {user_id}")

        return TranscriptionService(
            deepseek_config=deepseek_config,
            fireworks_config=fireworks_config
        )

    @staticmethod
    async def create_with_fallback(
        session: AsyncSession,
        user_id: int,
        use_default_on_missing: bool = False
    ) -> TranscriptionService:
        """
        Создать TranscriptionService с fallback на default credentials.

        Args:
            session: Database session
            user_id: ID пользователя
            use_default_on_missing: Использовать credentials по умолчанию если не найдены

        Returns:
            Настроенный TranscriptionService

        Raises:
            ValueError: Если credentials не найдены и fallback отключен
        """
        try:
            return await TranscriptionServiceFactory.create_for_user(session, user_id)
        except ValueError as e:
            if not use_default_on_missing:
                raise

            logger.warning(
                f"Failed to get user credentials: {e}. "
                f"Falling back to default credentials from config files."
            )

            # Fallback на credentials из файлов
            from deepseek_module import DeepSeekConfig
            from fireworks_module import FireworksConfig

            return TranscriptionService(
                deepseek_config=DeepSeekConfig.from_file(),
                fireworks_config=FireworksConfig.from_file()
            )

