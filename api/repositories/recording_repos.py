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
            local_video_path=kwargs.get("local_video_path"),
            processed_video_path=kwargs.get("processed_video_path"),
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

    async def get_or_create_output_target(
        self,
        recording: RecordingModel,
        target_type: str,
        preset_id: int | None = None,
    ) -> OutputTargetModel:
        """
        Получить или создать output_target.

        Args:
            recording: Запись
            target_type: Тип цели (YOUTUBE, VK)
            preset_id: ID output preset

        Returns:
            OutputTargetModel
        """
        from sqlalchemy import select

        from models.recording import TargetStatus

        # Ищем существующий output_target через явный DB query
        # (не полагаемся на recording.outputs - может быть не загружен)
        stmt = select(OutputTargetModel).where(
            OutputTargetModel.recording_id == recording.id,
            OutputTargetModel.target_type == target_type,
        )
        result = await self.session.execute(stmt)
        existing_output = result.scalar_one_or_none()

        if existing_output:
            logger.debug(f"Found existing output_target for recording {recording.id} to {target_type}")
            return existing_output

        # Создаем новый
        output = OutputTargetModel(
            recording_id=recording.id,
            user_id=recording.user_id,
            preset_id=preset_id,
            target_type=target_type,
            status=TargetStatus.NOT_UPLOADED,
            target_meta={},
        )

        self.session.add(output)
        await self.session.flush()

        logger.info(f"Created output_target for recording {recording.id} to {target_type}")
        return output

    async def mark_output_uploading(
        self,
        output_target: OutputTargetModel,
    ) -> None:
        """
        Пометить output_target как загружаемый.

        Args:
            output_target: Output target
        """
        from models.recording import TargetStatus

        output_target.status = TargetStatus.UPLOADING
        output_target.failed = False
        output_target.updated_at = datetime.utcnow()
        await self.session.flush()

        logger.debug(f"Marked output_target {output_target.id} as UPLOADING")

    async def mark_output_failed(
        self,
        output_target: OutputTargetModel,
        error_message: str,
    ) -> None:
        """
        Пометить output_target как failed.

        Args:
            output_target: Output target
            error_message: Сообщение об ошибке
        """
        from models.recording import TargetStatus

        output_target.status = TargetStatus.FAILED
        output_target.failed = True
        output_target.failed_at = datetime.utcnow()
        output_target.failed_reason = error_message[:1000]  # Ограничение длины
        output_target.retry_count += 1
        output_target.updated_at = datetime.utcnow()
        await self.session.flush()

        logger.warning(
            f"Marked output_target {output_target.id} as FAILED: {error_message[:100]}"
        )

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
        from sqlalchemy import select

        from models.recording import TargetStatus

        # Проверяем, есть ли уже output для этого target_type (явный DB query)
        stmt = select(OutputTargetModel).where(
            OutputTargetModel.recording_id == recording.id,
            OutputTargetModel.target_type == target_type,
        )
        result = await self.session.execute(stmt)
        existing_output = result.scalar_one_or_none()

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
            existing_output.failed = False
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

    async def find_by_source_key(
        self,
        user_id: int,
        source_type: SourceType,
        source_key: str,
        start_time: datetime,
    ) -> RecordingModel | None:
        """
        Найти запись по source_key, source_type и start_time.

        Args:
            user_id: ID пользователя
            source_type: Тип источника
            source_key: Ключ источника (meeting_id для Zoom)
            start_time: Время начала

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
            .join(SourceMetadataModel)
            .where(
                RecordingModel.user_id == user_id,
                SourceMetadataModel.source_type == source_type,
                SourceMetadataModel.source_key == source_key,
                RecordingModel.start_time == start_time,
            )
        )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_or_update(
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
    ) -> tuple[RecordingModel, bool]:
        """
        Создать или обновить запись (upsert логика).

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
            Tuple (запись, был_ли_создан_новый)
        """
        # Проверяем существующую запись
        existing = await self.find_by_source_key(user_id, source_type, source_key, start_time)

        if existing:
            # Обновляем существующую запись, но только если статус не UPLOADED
            if existing.status != ProcessingStatus.UPLOADED:
                existing.display_name = display_name
                existing.duration = duration
                existing.video_file_size = kwargs.get("video_file_size", existing.video_file_size)

                # Обновляем is_mapped если передан
                if "is_mapped" in kwargs:
                    old_is_mapped = existing.is_mapped
                    existing.is_mapped = kwargs["is_mapped"]

                    # Если is_mapped изменился, обновляем статус
                    if old_is_mapped != existing.is_mapped and existing.status in [ProcessingStatus.INITIALIZED, ProcessingStatus.SKIPPED]:
                        existing.status = ProcessingStatus.INITIALIZED if existing.is_mapped else ProcessingStatus.SKIPPED

                # Обновляем template_id если передан
                if "template_id" in kwargs:
                    existing.template_id = kwargs["template_id"]

                # Обновляем blank_record если передан
                if "blank_record" in kwargs:
                    existing.blank_record = kwargs["blank_record"]

                # Обновляем source metadata
                if existing.source:
                    existing_meta = existing.source.meta or {}
                    merged_meta = dict(existing_meta)
                    merged_meta.update(source_metadata or {})
                    existing.source.meta = merged_meta

                existing.updated_at = datetime.utcnow()

                logger.info(
                    f"Updated existing recording {existing.id} for user {user_id} (status={existing.status})"
                )

                await self.session.flush()
                return existing, False
            else:
                # Запись уже загружена, не обновляем
                logger.info(
                    f"Skipped updating recording {existing.id} - already uploaded"
                )
                return existing, False
        else:
            # Создаем новую запись
            is_mapped = kwargs.get("is_mapped", False)
            status = ProcessingStatus.INITIALIZED if is_mapped else ProcessingStatus.SKIPPED

            recording = RecordingModel(
                user_id=user_id,
                input_source_id=input_source_id,
                template_id=kwargs.get("template_id"),
                display_name=display_name,
                start_time=start_time,
                duration=duration,
                status=status,
                is_mapped=is_mapped,
                blank_record=kwargs.get("blank_record", False),
                video_file_size=kwargs.get("video_file_size"),
                expire_at=kwargs.get("expire_at"),
                local_video_path=kwargs.get("local_video_path"),
                processed_video_path=kwargs.get("processed_video_path"),
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
                f"Created new recording {recording.id} for user {user_id} (is_mapped={is_mapped}, status={status})"
            )

            return recording, True

    async def delete(self, recording: RecordingModel) -> None:
        """
        Удалить запись.

        Args:
            recording: Запись для удаления
        """
        await self.session.delete(recording)
        await self.session.flush()

        logger.info(f"Deleted recording {recording.id}")

