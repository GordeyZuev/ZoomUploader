"""Template, config, source and preset repositories"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.template_models import (
    BaseConfigModel,
    InputSourceModel,
    OutputPresetModel,
    RecordingTemplateModel,
)


class BaseConfigRepository:
    """Репозиторий для работы с базовыми конфигурациями."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_global(self) -> list[BaseConfigModel]:
        """Получение всех глобальных конфигураций."""
        result = await self.session.execute(
            select(BaseConfigModel).where(BaseConfigModel.user_id.is_(None), BaseConfigModel.is_active)
        )
        return list(result.scalars().all())

    async def find_by_user(self, user_id: int) -> list[BaseConfigModel]:
        """Получение конфигураций пользователя."""
        result = await self.session.execute(
            select(BaseConfigModel).where(BaseConfigModel.user_id == user_id, BaseConfigModel.is_active)
        )
        return list(result.scalars().all())

    async def find_by_id(self, config_id: int, user_id: int | None = None) -> BaseConfigModel | None:
        """Получение конфигурации по ID с проверкой прав."""
        query = select(BaseConfigModel).where(BaseConfigModel.id == config_id)
        if user_id is not None:
            # Пользователь может видеть только свои конфигурации или глобальные
            query = query.where(
                (BaseConfigModel.user_id == user_id) | (BaseConfigModel.user_id.is_(None))
            )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int | None,
        name: str,
        config_data: dict[str, Any],
        description: str | None = None,
        config_type: str | None = None,
    ) -> BaseConfigModel:
        """Создание новой конфигурации."""
        config = BaseConfigModel(
            user_id=user_id,
            name=name,
            description=description,
            config_type=config_type,
            config_data=config_data,
        )
        self.session.add(config)
        await self.session.flush()
        return config

    async def update(self, config: BaseConfigModel) -> BaseConfigModel:
        """Обновление конфигурации."""
        config.updated_at = datetime.utcnow()
        await self.session.flush()
        return config

    async def delete(self, config: BaseConfigModel) -> None:
        """Удаление конфигурации."""
        await self.session.delete(config)
        await self.session.flush()


class InputSourceRepository:
    """Репозиторий для работы с источниками данных."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_user(self, user_id: int) -> list[InputSourceModel]:
        """Получение всех источников пользователя."""
        result = await self.session.execute(
            select(InputSourceModel).where(InputSourceModel.user_id == user_id)
        )
        return list(result.scalars().all())

    async def find_by_id(self, source_id: int, user_id: int) -> InputSourceModel | None:
        """Получение источника по ID с проверкой прав."""
        result = await self.session.execute(
            select(InputSourceModel).where(
                InputSourceModel.id == source_id,
                InputSourceModel.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def find_active_by_user(self, user_id: int) -> list[InputSourceModel]:
        """Получение активных источников пользователя."""
        result = await self.session.execute(
            select(InputSourceModel).where(
                InputSourceModel.user_id == user_id,
                InputSourceModel.is_active
            )
        )
        return list(result.scalars().all())

    async def find_duplicate(
        self,
        user_id: int,
        name: str,
        source_type: str,
        credential_id: int | None,
    ) -> InputSourceModel | None:
        """
        Поиск дубликата источника.

        Источник считается дубликатом, если у пользователя уже есть источник с таким же:
        - name
        - source_type
        - credential_id
        """
        query = select(InputSourceModel).where(
            InputSourceModel.user_id == user_id,
            InputSourceModel.name == name,
            InputSourceModel.source_type == source_type,
        )

        if credential_id is not None:
            query = query.where(InputSourceModel.credential_id == credential_id)
        else:
            query = query.where(InputSourceModel.credential_id.is_(None))

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create(
        self,
        user_id: int,
        name: str,
        source_type: str,
        credential_id: int | None = None,
        config: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> InputSourceModel:
        """Создание нового источника."""
        source = InputSourceModel(
            user_id=user_id,
            name=name,
            source_type=source_type,
            credential_id=credential_id,
            config=config,
            description=description,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def update(self, source: InputSourceModel) -> InputSourceModel:
        """Обновление источника."""
        source.updated_at = datetime.utcnow()
        await self.session.flush()
        return source

    async def update_last_sync(self, source: InputSourceModel) -> InputSourceModel:
        """Обновление времени последней синхронизации."""
        source.last_sync_at = datetime.utcnow()
        await self.session.flush()
        return source

    async def delete(self, source: InputSourceModel) -> None:
        """Удаление источника."""
        await self.session.delete(source)
        await self.session.flush()


class OutputPresetRepository:
    """Репозиторий для работы с пресетами выгрузки."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_user(self, user_id: int) -> list[OutputPresetModel]:
        """Получение всех пресетов пользователя."""
        result = await self.session.execute(
            select(OutputPresetModel).where(OutputPresetModel.user_id == user_id)
        )
        return list(result.scalars().all())

    async def find_by_id(self, preset_id: int, user_id: int) -> OutputPresetModel | None:
        """Получение пресета по ID с проверкой прав."""
        result = await self.session.execute(
            select(OutputPresetModel).where(
                OutputPresetModel.id == preset_id,
                OutputPresetModel.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def find_active_by_user(self, user_id: int) -> list[OutputPresetModel]:
        """Получение активных пресетов пользователя."""
        result = await self.session.execute(
            select(OutputPresetModel).where(
                OutputPresetModel.user_id == user_id,
                OutputPresetModel.is_active
            )
        )
        return list(result.scalars().all())

    async def find_by_platform(self, user_id: int, platform: str) -> list[OutputPresetModel]:
        """Получение пресетов по платформе."""
        result = await self.session.execute(
            select(OutputPresetModel).where(
                OutputPresetModel.user_id == user_id,
                OutputPresetModel.platform == platform,
                OutputPresetModel.is_active
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        name: str,
        platform: str,
        credential_id: int,
        preset_metadata: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> OutputPresetModel:
        """Создание нового пресета."""
        preset = OutputPresetModel(
            user_id=user_id,
            name=name,
            platform=platform,
            credential_id=credential_id,
            preset_metadata=preset_metadata,
            description=description,
        )
        self.session.add(preset)
        await self.session.flush()
        return preset

    async def update(self, preset: OutputPresetModel) -> OutputPresetModel:
        """Обновление пресета."""
        preset.updated_at = datetime.utcnow()
        await self.session.flush()
        return preset

    async def delete(self, preset: OutputPresetModel) -> None:
        """Удаление пресета."""
        await self.session.delete(preset)
        await self.session.flush()


class RecordingTemplateRepository:
    """Репозиторий для работы с шаблонами записей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_user(self, user_id: int, include_drafts: bool = False) -> list[RecordingTemplateModel]:
        """Получение всех шаблонов пользователя."""
        query = select(RecordingTemplateModel).where(RecordingTemplateModel.user_id == user_id)
        if not include_drafts:
            query = query.where(~RecordingTemplateModel.is_draft)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def find_by_id(self, template_id: int, user_id: int) -> RecordingTemplateModel | None:
        """Получение шаблона по ID с проверкой прав."""
        result = await self.session.execute(
            select(RecordingTemplateModel).where(
                RecordingTemplateModel.id == template_id,
                RecordingTemplateModel.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def find_active_by_user(self, user_id: int) -> list[RecordingTemplateModel]:
        """Получение активных шаблонов пользователя, отсортированных по created_at ASC (first-match strategy)."""
        result = await self.session.execute(
            select(RecordingTemplateModel)
            .where(
                RecordingTemplateModel.user_id == user_id,
                RecordingTemplateModel.is_active,
                ~RecordingTemplateModel.is_draft
            )
            .order_by(RecordingTemplateModel.created_at.asc())
        )
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        name: str,
        matching_rules: dict[str, Any] | None = None,
        processing_config: dict[str, Any] | None = None,
        metadata_config: dict[str, Any] | None = None,
        output_config: dict[str, Any] | None = None,
        description: str | None = None,
        is_draft: bool = False,
    ) -> RecordingTemplateModel:
        """Создание нового шаблона."""
        template = RecordingTemplateModel(
            user_id=user_id,
            name=name,
            description=description,
            matching_rules=matching_rules,
            processing_config=processing_config,
            metadata_config=metadata_config,
            output_config=output_config,
            is_draft=is_draft,
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def update(self, template: RecordingTemplateModel) -> RecordingTemplateModel:
        """Обновление шаблона."""
        template.updated_at = datetime.utcnow()
        await self.session.flush()
        return template

    async def increment_usage(self, template: RecordingTemplateModel) -> RecordingTemplateModel:
        """Увеличение счетчика использования."""
        template.used_count += 1
        template.last_used_at = datetime.utcnow()
        await self.session.flush()
        return template

    async def delete(self, template: RecordingTemplateModel) -> None:
        """Удаление шаблона."""
        await self.session.delete(template)
        await self.session.flush()

