"""Helper для получения параметров из user_config и template.

Используется для определения allow_skipped и других runtime параметров.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.config_repos import UserConfigRepository
from api.repositories.template_repos import RecordingTemplateRepository


async def get_allow_skipped_flag(
    session: AsyncSession,
    user_id: int,
    template_id: int | None = None,
    explicit_value: bool | None = None,
) -> bool:
    """
    Получить флаг allow_skipped из конфигурации.

    Приоритет (от высшего к низшему):
    1. Явно переданный параметр (explicit_value)
    2. Template.processing_config.allow_skipped
    3. User config.processing.allow_skipped
    4. Default: False

    Args:
        session: DB session
        user_id: ID пользователя
        template_id: ID шаблона (опционально)
        explicit_value: Явно переданное значение из query param

    Returns:
        bool - разрешить обработку SKIPPED записей
    """
    # 1. Явно переданный параметр имеет высший приоритет
    if explicit_value is not None:
        return explicit_value

    # 2. Проверяем template (если указан)
    if template_id is not None:
        template_repo = RecordingTemplateRepository(session)
        template = await template_repo.get_by_id(template_id, user_id)
        if template and template.processing_config:
            allow_skipped = template.processing_config.get("allow_skipped")
            if allow_skipped is not None:
                return bool(allow_skipped)

    # 3. Проверяем user config
    try:
        user_config_repo = UserConfigRepository(session)
        user_config = await user_config_repo.get_user_config(user_id)
        if user_config:
            processing_config = user_config.get("processing", {})
            allow_skipped = processing_config.get("allow_skipped")
            if allow_skipped is not None:
                return bool(allow_skipped)
    except Exception:
        # Если нет user_config, продолжаем
        pass

    # 4. Default: False (не разрешаем обработку SKIPPED)
    return False


async def get_user_processing_config(
    session: AsyncSession,
    user_id: int,
) -> dict[str, Any]:
    """
    Получить processing конфигурацию пользователя.

    Args:
        session: DB session
        user_id: ID пользователя

    Returns:
        dict с конфигурацией processing
    """
    try:
        user_config_repo = UserConfigRepository(session)
        user_config = await user_config_repo.get_user_config(user_id)
        if user_config:
            return user_config.get("processing", {})
    except Exception:
        pass

    return {}

