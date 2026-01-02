"""Async repository для работы с recordings с multi-tenancy."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import OutputTargetModel, RecordingModel, SourceMetadataModel
from logger import get_logger
from models.recording import ProcessingStatus, SourceType

logger = get_logger()


class RecordingAsyncRepository:
    """Async репозиторий для работы с recordings."""

    def __init__(self, session: AsyncSession):
        """
        Инициализация репозитория.

        Args:
            session: Async database session
        """
        self.session = session

    async def get_by_id(self, recording_id: int, user_id: int) -> RecordingModel | None:
        """
        Получить запись по ID с проверкой принадлежности пользователю.

        Args:
            recording_id: ID записи
            user_id: ID пользователя

        Returns:
            Recording или None
        """
        query = (
            select(RecordingModel)
            .options(
                selectinload(RecordingModel.source),
                selectinload(RecordingModel.outputs),
                selectinload(RecordingModel.processing_stages),
                selectinload(RecordingModel.input_source),
            )
            .where(
                RecordingModel.id == recording_id,
                RecordingModel.user_id == user_id,
            )
        )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: int,
        status: ProcessingStatus | None = None,
        input_source_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[RecordingModel]:
        """
        Получить список записей пользователя.

        Args:
            user_id: ID пользователя
            status: Фильтр по статусу
            input_source_id: Фильтр по источнику
            limit: Лимит записей
            offset: Смещение

        Returns:
            Список recordings
        """
        query = (
            select(RecordingModel)
            .options(
                selectinload(RecordingModel.source),
                selectinload(RecordingModel.outputs),
                selectinload(RecordingModel.input_source),
            )
            .where(RecordingModel.user_id == user_id)
            .order_by(RecordingModel.start_time.desc())
            .limit(limit)
            .offset(offset)
        )

        if status:
            query = query.where(RecordingModel.status == status)

        if input_source_id:
            query = query.where(RecordingModel.input_source_id == input_source_id)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        user_id: int,
        input_source_id: int | None,
        display_name: str,
        start_time: datetime,
        duration: int,
        source_type: SourceType,
        source_key: str,
        source_metadata: dict[str, Any] | None = None,
        **kwargs,
    ) -> RecordingModel:
        """
        Создать новую запись.

        Args:
            user_id: ID пользователя
            input_source_id: ID источника
            display_name: Название записи
            start_time: Время начала
            duration: Длительность
            source_type: Тип источника
            source_key: Ключ источника
            source_metadata: Метаданные источника
            **kwargs: Дополнительные поля

        Returns:
            Созданная запись
        """
        recording = RecordingModel(
            user_id=user_id,
            input_source_id=input_source_id,
            display_name=display_name,
            start_time=start_time,
            duration=duration,
            status=kwargs.get("status", ProcessingStatus.INITIALIZED),
            is_mapped=kwargs.get("is_mapped", False),
            video_file_size=kwargs.get("video_file_size"),
            expire_at=kwargs.get("expire_at"),
        )

        self.session.add(recording)
        await self.session.flush()

        # Создаем source metadata
        source = SourceMetadataModel(
            recording_id=recording.id,
            user_id=user_id,
            input_source_id=input_source_id,
            source_type=source_type,
            source_key=source_key,
            meta=source_metadata or {},
        )

        self.session.add(source)
        await self.session.flush()

        logger.info(
            f"Created recording {recording.id} for user {user_id} from source {input_source_id}"
        )

        return recording

    async def update(
        self,
        recording: RecordingModel,
        **fields,
    ) -> RecordingModel:
        """
        Обновить запись.

        Args:
            recording: Запись для обновления
            **fields: Поля для обновления

        Returns:
            Обновленная запись
        """
        for field, value in fields.items():
            if hasattr(recording, field):
                setattr(recording, field, value)

        recording.updated_at = datetime.utcnow()
        await self.session.flush()

        logger.debug(f"Updated recording {recording.id}")
        return recording

    async def save_transcription_result(
        self,
        recording: RecordingModel,
        transcription_dir: str,
        transcription_info: dict[str, Any],
        topic_timestamps: list[dict[str, Any]],
        main_topics: list[str],
    ) -> RecordingModel:
        """
        Сохранить результаты транскрибации.

        Args:
            recording: Запись
            transcription_dir: Директория с транскрипцией
            transcription_info: Информация о транскрипции
            topic_timestamps: Временные метки тем
            main_topics: Основные темы

        Returns:
            Обновленная запись
        """
        recording.transcription_dir = transcription_dir
        recording.transcription_info = transcription_info
        recording.topic_timestamps = topic_timestamps
        recording.main_topics = main_topics
        recording.status = ProcessingStatus.TRANSCRIBED
        recording.updated_at = datetime.utcnow()

        await self.session.flush()

        logger.info(f"Saved transcription results for recording {recording.id}")
        return recording

    async def save_upload_result(
        self,
        recording: RecordingModel,
        target_type: str,
        preset_id: int | None,
        video_id: str,
        video_url: str,
        target_meta: dict[str, Any] | None = None,
    ) -> OutputTargetModel:
        """
        Сохранить результаты загрузки.

        Args:
            recording: Запись
            target_type: Тип цели (YOUTUBE, VK)
            preset_id: ID output preset
            video_id: ID видео на платформе
            video_url: URL видео
            target_meta: Метаданные

        Returns:
            OutputTarget
        """
        from models.recording import TargetStatus

        # Проверяем, есть ли уже output для этого target_type
        existing_output = None
        for output in recording.outputs:
            if output.target_type == target_type:
                existing_output = output
                break

        if existing_output:
            # Обновляем существующий
            existing_output.status = TargetStatus.UPLOADED
            existing_output.preset_id = preset_id
            existing_output.target_meta = {
                **(existing_output.target_meta or {}),
                "video_id": video_id,
                "video_url": video_url,
                **(target_meta or {}),
            }
            existing_output.uploaded_at = datetime.utcnow()
            existing_output.updated_at = datetime.utcnow()
            await self.session.flush()

            logger.info(
                f"Updated upload result for recording {recording.id} to {target_type}"
            )
            return existing_output
        else:
            # Создаем новый
            output = OutputTargetModel(
                recording_id=recording.id,
                user_id=recording.user_id,
                preset_id=preset_id,
                target_type=target_type,
                status=TargetStatus.UPLOADED,
                target_meta={
                    "video_id": video_id,
                    "video_url": video_url,
                    **(target_meta or {}),
                },
                uploaded_at=datetime.utcnow(),
            )

            self.session.add(output)
            await self.session.flush()

            logger.info(
                f"Created upload result for recording {recording.id} to {target_type}"
            )
            return output

    async def count_by_user(self, user_id: int, status: ProcessingStatus | None = None) -> int:
        """
        Подсчитать количество записей пользователя.

        Args:
            user_id: ID пользователя
            status: Фильтр по статусу

        Returns:
            Количество записей
        """
        from sqlalchemy import func

        query = select(func.count(RecordingModel.id)).where(RecordingModel.user_id == user_id)

        if status:
            query = query.where(RecordingModel.status == status)

        result = await self.session.execute(query)
        return result.scalar() or 0

    async def delete(self, recording: RecordingModel) -> None:
        """
        Удалить запись.

        Args:
            recording: Запись для удаления
        """
        await self.session.delete(recording)
        await self.session.flush()

        logger.info(f"Deleted recording {recording.id}")

