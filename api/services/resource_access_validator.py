"""Service for validating user access to various resources.

Централизованная валидация доступа к ресурсам (credentials, presets, sources)
для обеспечения изоляции данных между пользователями (multi-tenancy).
"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.auth_repos import UserCredentialRepository
from api.repositories.template_repos import InputSourceRepository, OutputPresetRepository
from logger import get_logger

logger = get_logger()


class ResourceAccessValidator:
    """
    Сервис для валидации доступа к ресурсам.

    Обеспечивает:
    - Проверку владения credential
    - Проверку владения source
    - Проверку владения preset
    - Легко расширяется на новые типы ресурсов

    Использование:
        validator = ResourceAccessValidator(session)
        await validator.validate_credential_access(credential_id, user_id)
    """

    def __init__(self, session: AsyncSession):
        """
        Инициализация валидатора.

        Args:
            session: Database session
        """
        self.session = session
        self._cred_repo: UserCredentialRepository | None = None
        self._source_repo: InputSourceRepository | None = None
        self._preset_repo: OutputPresetRepository | None = None

    @property
    def cred_repo(self) -> UserCredentialRepository:
        """Lazy-loaded credential repository."""
        if self._cred_repo is None:
            self._cred_repo = UserCredentialRepository(self.session)
        return self._cred_repo

    @property
    def source_repo(self) -> InputSourceRepository:
        """Lazy-loaded source repository."""
        if self._source_repo is None:
            self._source_repo = InputSourceRepository(self.session)
        return self._source_repo

    @property
    def preset_repo(self) -> OutputPresetRepository:
        """Lazy-loaded preset repository."""
        if self._preset_repo is None:
            self._preset_repo = OutputPresetRepository(self.session)
        return self._preset_repo

    async def validate_credential_access(
        self,
        credential_id: int,
        user_id: int,
        error_detail: str | None = None,
    ) -> None:
        """
        Проверить, что credential принадлежит пользователю.

        Args:
            credential_id: ID credential для проверки
            user_id: ID пользователя
            error_detail: Кастомное сообщение об ошибке (опционально)

        Raises:
            HTTPException: Если credential не найден или не принадлежит пользователю
        """
        credential = await self.cred_repo.get_by_id(credential_id)

        if not credential:
            logger.warning(f"Credential {credential_id} not found (requested by user {user_id})")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail or f"Credential {credential_id} not found",
            )

        if credential.user_id != user_id:
            logger.warning(
                f"User {user_id} attempted to access credential {credential_id} owned by user {credential.user_id}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail or "Access denied. This credential belongs to another user.",
            )

        logger.debug(f"User {user_id} validated access to credential {credential_id}")

    async def validate_source_access(
        self,
        source_id: int,
        user_id: int,
        error_detail: str | None = None,
    ) -> None:
        """
        Проверить, что source принадлежит пользователю.

        Args:
            source_id: ID source для проверки
            user_id: ID пользователя
            error_detail: Кастомное сообщение об ошибке (опционально)

        Raises:
            HTTPException: Если source не найден или не принадлежит пользователю
        """
        source = await self.source_repo.find_by_id(source_id, user_id)

        if not source:
            logger.warning(f"Source {source_id} not found for user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail or f"Source {source_id} not found",
            )

        logger.debug(f"User {user_id} validated access to source {source_id}")

    async def validate_preset_access(
        self,
        preset_id: int,
        user_id: int,
        error_detail: str | None = None,
    ) -> None:
        """
        Проверить, что preset принадлежит пользователю.

        Args:
            preset_id: ID preset для проверки
            user_id: ID пользователя
            error_detail: Кастомное сообщение об ошибке (опционально)

        Raises:
            HTTPException: Если preset не найден или не принадлежит пользователю
        """
        preset = await self.preset_repo.find_by_id(preset_id, user_id)

        if not preset:
            logger.warning(f"Preset {preset_id} not found for user {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail or f"Preset {preset_id} not found",
            )

        logger.debug(f"User {user_id} validated access to preset {preset_id}")

    async def validate_credential_for_update(
        self,
        credential_id: int | None,
        user_id: int,
        resource_name: str = "resource",
    ) -> None:
        """
        Проверить credential при обновлении ресурса.

        Используется в PATCH endpoints для sources и presets.
        Если credential_id=None, проверка пропускается (credential не обновляется).

        Args:
            credential_id: ID credential или None
            user_id: ID пользователя
            resource_name: Название ресурса для логирования

        Raises:
            HTTPException: Если credential не принадлежит пользователю
        """
        if credential_id is None:
            # Credential не обновляется, пропускаем проверку
            return

        await self.validate_credential_access(
            credential_id,
            user_id,
            error_detail=f"Cannot update {resource_name}: credential {credential_id} not found or access denied",
        )
