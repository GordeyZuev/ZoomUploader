"""Service Context для передачи user_id и session через все сервисы.

Реализует паттерн Context Object для избежания передачи множества параметров
через цепочку вызовов функций (KISS + DRY).
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.helpers.config_helper import ConfigHelper


@dataclass
class ServiceContext:
    """
    Контекст выполнения операции для пользователя.

    Централизует доступ к session, user_id и config_helper,
    избегая передачи множества параметров.
    """

    session: AsyncSession
    user_id: int

    def __post_init__(self):
        """Инициализация config_helper."""
        self._config_helper: ConfigHelper | None = None

    @property
    def config_helper(self) -> ConfigHelper:
        """
        Lazy-loaded ConfigHelper для доступа к credentials.

        Returns:
            ConfigHelper для текущего пользователя
        """
        if self._config_helper is None:
            self._config_helper = ConfigHelper(self.session, self.user_id)
        return self._config_helper

    @classmethod
    def create(cls, session: AsyncSession, user_id: int) -> "ServiceContext":
        """
        Factory method для создания контекста.

        Args:
            session: Database session
            user_id: ID пользователя

        Returns:
            Новый ServiceContext
        """
        return cls(session=session, user_id=user_id)

