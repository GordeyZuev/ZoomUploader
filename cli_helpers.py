"""Helper functions для CLI с поддержкой multi-tenancy.

Обеспечивает работу CLI с user-specific credentials из БД.
"""


from api.core.context import ServiceContext
from api.helpers.config_helper import ConfigHelper
from config.settings import ZoomConfig
from database.config import DatabaseConfig
from database.manager import DatabaseManager
from logger import get_logger

logger = get_logger()


async def get_zoom_config_for_cli(
    user_id: int,
    account_name: str | None = None
) -> ZoomConfig:
    """
    Получить ZoomConfig для CLI.

    Args:
        user_id: ID пользователя
        account_name: Имя аккаунта (опционально)

    Returns:
        ZoomConfig с credentials пользователя

    Raises:
        ValueError: Если credentials не найдены
    """
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    async with db_manager.async_session() as session:
        config_helper = ConfigHelper(session, user_id)
        zoom_config = await config_helper.get_zoom_config(account_name)
        logger.info(f"Retrieved Zoom config for user {user_id}, account: {account_name or 'default'}")
        return zoom_config


async def get_service_context_for_cli(user_id: int) -> ServiceContext:
    """
    Создать ServiceContext для CLI.

    Args:
        user_id: ID пользователя

    Returns:
        ServiceContext для использования в CLI

    Raises:
        ValueError: Если пользователь не найден
    """
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)

    # Проверяем существование пользователя
    async with db_manager.async_session() as session:
        user = await db_manager.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"User {user_id} not found in database")

        if not user.is_active:
            raise ValueError(f"User {user_id} is not active")

        logger.info(f"Created service context for user {user_id} ({user.email})")
        return ServiceContext.create(session=session, user_id=user_id)


def add_user_id_option(f):
    """
    Декоратор для добавления --user-id опции к CLI команде.

    Пример использования:
    @cli.command()
    @add_user_id_option
    def my_command(user_id: int, ...):
        ...
    """
    import click
    return click.option(
        "--user-id",
        type=int,
        required=True,
        help="ID пользователя для выполнения операции"
    )(f)


def add_account_name_option(f):
    """
    Декоратор для добавления --account-name опции к CLI команде.

    Используется для выбора конкретного аккаунта Zoom, если у пользователя
    несколько аккаунтов на одной платформе.
    """
    import click
    return click.option(
        "--account-name",
        type=str,
        default=None,
        help="Имя аккаунта (для множественных аккаунтов на одной платформе)"
    )(f)

