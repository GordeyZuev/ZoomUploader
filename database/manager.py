import os
import shutil
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import asyncpg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from logger import get_logger
from models.recording import (
    MeetingRecording,
    OutputTarget,
    ProcessingStage,
    ProcessingStageStatus,
    ProcessingStageType,
    ProcessingStatus,
    SourceType,
    TargetStatus,
    TargetType,
    _normalize_enum,
)

from .config import DatabaseConfig
from .models import (
    Base,
    OutputTargetModel,
    ProcessingStageModel,
    RecordingModel,
    SourceMetadataModel,
)

logger = get_logger()


def _parse_start_time(start_time_str: str) -> datetime:
    """Парсинг строки start_time в datetime объект (формат Zoom: 2021-03-18T05:41:36Z)."""
    if not start_time_str:
        raise ValueError("start_time не может быть пустым")

    try:
        if start_time_str.endswith("Z"):
            time_str = start_time_str[:-1] + "+00:00"
        else:
            time_str = start_time_str

        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    except Exception as e:
        logger.error(f"Ошибка парсинга start_time '{start_time_str}': {e}")
        raise ValueError(f"Не удалось распарсить start_time: {start_time_str}") from e


def _build_source_metadata_payload(recording: MeetingRecording) -> dict:
    """Формирует JSONB метаданных источника из модели."""
    meta = dict(recording.source_metadata or {})

    # Основные поля Zoom (для обратной совместимости)
    zoom_fields = {
        "meeting_id": getattr(recording, "meeting_id", None),
        "account": getattr(recording, "account", None),
        "video_file_download_url": getattr(recording, "video_file_download_url", None),
        "download_url": getattr(recording, "video_file_download_url", None),  # Алиас
        "download_access_token": getattr(recording, "download_access_token", None),
        "password": getattr(recording, "password", None),
        "recording_play_passcode": getattr(recording, "recording_play_passcode", None),
        "part_index": getattr(recording, "part_index", None),
        "total_visible_parts": getattr(recording, "total_visible_parts", None),
    }
    for key, value in zoom_fields.items():
        if value:
            meta[key] = value

    if recording.video_file_size is not None:
        meta["video_file_size"] = recording.video_file_size

    return meta


class DatabaseManager:
    """Менеджер для работы с базой данных."""

    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.engine = create_async_engine(config.url, echo=False)
        self.async_session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def create_database_if_not_exists(self):
        """Создание базы данных, если она не существует."""
        try:
            parsed = urlparse(self.config.url)

            conn = await asyncpg.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database="postgres",
            )

            result = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", self.config.database)

            if not result:
                await conn.execute(f'CREATE DATABASE "{self.config.database}"')
                logger.info(f"База данных создана: database={self.config.database}")

            await conn.close()

        except Exception as e:
            logger.error(f"Ошибка создания базы данных: database={self.config.database} | error={e}")
            raise

    async def recreate_database(self):
        """Полное пересоздание базы данных: удаление и создание заново."""
        try:
            parsed = urlparse(self.config.url)

            # Закрываем все активные соединения с текущей БД (если они есть)
            try:
                await self.close()
            except Exception:
                # Игнорируем ошибки при закрытии, если engine еще не использовался
                pass

            # Подключаемся к системной базе данных postgres
            conn = await asyncpg.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database="postgres",
            )

            # Проверяем, существует ли база данных
            db_exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", self.config.database)

            if db_exists:
                # Завершаем все активные соединения к целевой БД
                # Используем параметризованный запрос для безопасности
                try:
                    await conn.execute(
                        """
                        SELECT pg_terminate_backend(pg_stat_activity.pid)
                        FROM pg_stat_activity
                        WHERE pg_stat_activity.datname = $1
                        AND pid <> pg_backend_pid()
                    """,
                        self.config.database,
                    )
                except Exception as e:
                    logger.warning(f"Не удалось завершить все соединения: database={self.config.database} | error={e}")

                db_name_quoted = self.config.database.replace('"', '""')
                await conn.execute(f'DROP DATABASE IF EXISTS "{db_name_quoted}"')
                logger.info(f"База данных удалена: database={self.config.database}")

            db_name_quoted = self.config.database.replace('"', '""')
            await conn.execute(f'CREATE DATABASE "{db_name_quoted}"')
            logger.info(f"База данных создана: database={self.config.database}")

            await conn.close()

            self.engine = create_async_engine(self.config.url, echo=False)
            self.async_session = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

            await self.create_tables()

            logger.info(f"База данных полностью пересоздана: database={self.config.database}")

        except Exception as e:
            logger.error(f"Ошибка пересоздания базы данных: database={self.config.database} | error={e}")
            raise

    async def create_tables(self):
        """Создание таблиц в базе данных."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Таблицы созданы")
        except Exception as e:
            logger.error(f"Ошибка создания таблиц: error={e}")
            raise

    async def save_recordings(self, recordings: list[MeetingRecording]) -> int:
        """Сохранение записей в базу данных."""
        if not recordings:
            return 0

        saved_count = 0
        async with self.async_session() as session:
            try:
                for recording in recordings:
                    try:
                        existing = await self._find_existing_recording(session, recording)
                        if existing:
                            await self._update_existing_recording(session, existing, recording)
                        else:
                            await self._create_new_recording(session, recording)
                        saved_count += 1
                    except IntegrityError as e:
                        logger.warning(
                            f"Запись уже существует: recording={recording.display_name} | recording_id={recording.db_id} | error={e}"
                        )
                        await session.rollback()
                        continue
                    except Exception as e:
                        logger.error(
                            f"Ошибка сохранения записи: recording={recording.display_name} | recording_id={recording.db_id} | error={e}"
                        )
                        await session.rollback()
                        continue

                await session.commit()
                logger.info(f"Сохранено записей: {saved_count}/{len(recordings)}")
                return saved_count

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка транзакции: error={e}")
                raise

    async def _find_existing_recording(
        self, session: AsyncSession, recording: MeetingRecording
    ) -> RecordingModel | None:
        """Поиск существующей записи по (source_type, source_key, start_time)."""
        try:
            start_time = _parse_start_time(recording.start_time)
            source_type = _normalize_enum(recording.source_type, SourceType)
            stmt = (
                select(RecordingModel)
                .options(
                    selectinload(RecordingModel.source),
                    selectinload(RecordingModel.outputs),
                    selectinload(RecordingModel.processing_stages),
                )
                .join(SourceMetadataModel)
                .where(
                    SourceMetadataModel.source_type == source_type,
                    SourceMetadataModel.source_key == recording.source_key,
                    RecordingModel.start_time == start_time,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(
                f"Ошибка поиска существующей записи: source_type={recording.source_type} | source_key={recording.source_key} | error={e}"
            )
            return None

    async def _update_existing_recording(
        self, session: AsyncSession, existing: RecordingModel, recording: MeetingRecording
    ):
        """Обновление существующей записи."""
        existing.display_name = recording.display_name
        existing.duration = recording.duration
        existing.video_file_size = recording.video_file_size
        existing.is_mapped = recording.is_mapped if recording.is_mapped is not None else existing.is_mapped

        new_status = _normalize_enum(recording.status, ProcessingStatus)

        if existing.status != new_status and existing.status != ProcessingStatus.UPLOADED:
            existing.status = new_status
        existing.expire_at = recording.expire_at

        existing.local_video_path = recording.local_video_path
        existing.processed_video_path = recording.processed_video_path
        existing.processed_audio_dir = recording.processed_audio_dir
        existing.transcription_dir = recording.transcription_dir
        existing.transcription_info = recording.transcription_info
        existing.topic_timestamps = recording.topic_timestamps
        existing.main_topics = recording.main_topics
        existing.processing_preferences = recording.processing_preferences
        existing.downloaded_at = recording.downloaded_at

        existing.failed = recording.failed
        existing.failed_at = recording.failed_at
        existing.failed_reason = recording.failed_reason
        existing.failed_at_stage = recording.failed_at_stage
        existing.retry_count = recording.retry_count

        meta = _build_source_metadata_payload(recording)
        if existing.source is None:
            source = SourceMetadataModel(
                recording_id=existing.id,
                source_type=_normalize_enum(recording.source_type, SourceType),
                source_key=recording.source_key,
                meta=meta,
            )
            session.add(source)
        else:
            existing.source.source_type = _normalize_enum(recording.source_type, SourceType)
            existing.source.source_key = recording.source_key
            existing_meta = existing.source.meta or {}
            merged_meta = dict(existing_meta)
            merged_meta.update(meta)
            existing.source.meta = merged_meta

        existing_outputs: dict[TargetType, OutputTargetModel] = {}
        for out in existing.outputs:
            key = _normalize_enum(out.target_type, TargetType)
            existing_outputs[key] = out

        for target in recording.output_targets:
            target_type_value = _normalize_enum(target.target_type, TargetType)
            db_target = existing_outputs.get(target_type_value)
            target_status = _normalize_enum(target.status, TargetStatus)
            if db_target:
                db_target.status = target_status
                db_target.target_meta = target.target_meta
                db_target.uploaded_at = target.uploaded_at
            else:
                session.add(
                    OutputTargetModel(
                        recording_id=existing.id,
                        target_type=target_type_value,
                        status=target_status,
                        target_meta=target.target_meta,
                        uploaded_at=target.uploaded_at,
                    )
                )

        existing_stages: dict[ProcessingStageType, ProcessingStageModel] = {}
        for stage in existing.processing_stages:
            key = _normalize_enum(stage.stage_type, ProcessingStageType)
            existing_stages[key] = stage

        for stage in recording.processing_stages:
            stage_type_value = _normalize_enum(stage.stage_type, ProcessingStageType)
            stage_status = _normalize_enum(stage.status, ProcessingStageStatus)
            db_stage = existing_stages.get(stage_type_value)
            if db_stage:
                db_stage.status = stage_status
                db_stage.failed = stage.failed
                db_stage.failed_at = stage.failed_at
                db_stage.failed_reason = stage.failed_reason
                db_stage.retry_count = stage.retry_count
                db_stage.stage_meta = stage.stage_meta
                db_stage.completed_at = stage.completed_at
            else:
                session.add(
                    ProcessingStageModel(
                        recording_id=existing.id,
                        stage_type=stage_type_value,
                        status=stage_status,
                        failed=stage.failed,
                        failed_at=stage.failed_at,
                        failed_reason=stage.failed_reason,
                        retry_count=stage.retry_count,
                        stage_meta=stage.stage_meta,
                        completed_at=stage.completed_at,
                    )
                )

        existing.updated_at = datetime.now()
        session.add(existing)

    async def _create_new_recording(self, session: AsyncSession, recording: MeetingRecording):
        """Создание новой записи."""
        db_recording = RecordingModel(
            display_name=recording.display_name,
            start_time=_parse_start_time(recording.start_time),
            duration=recording.duration,
            status=recording.status,
            is_mapped=recording.is_mapped,
            expire_at=recording.expire_at,
            local_video_path=recording.local_video_path,
            processed_video_path=recording.processed_video_path,
            processed_audio_dir=recording.processed_audio_dir,
            transcription_dir=recording.transcription_dir,
            video_file_size=recording.video_file_size,
            transcription_info=recording.transcription_info,
            topic_timestamps=recording.topic_timestamps,
            main_topics=recording.main_topics,
            processing_preferences=recording.processing_preferences,
            downloaded_at=recording.downloaded_at,
            failed=recording.failed,
            failed_at=recording.failed_at,
            failed_reason=recording.failed_reason,
            failed_at_stage=recording.failed_at_stage,
            retry_count=recording.retry_count,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        session.add(db_recording)
        await session.flush()
        recording.db_id = db_recording.id

        meta = _build_source_metadata_payload(recording)
        source_model = SourceMetadataModel(
            recording_id=db_recording.id,
            source_type=_normalize_enum(recording.source_type, SourceType),
            source_key=recording.source_key,
            meta=meta,
        )
        session.add(source_model)
        await session.flush()

        for target in recording.output_targets:
            session.add(
                OutputTargetModel(
                    recording_id=db_recording.id,
                    target_type=_normalize_enum(target.target_type, TargetType),
                    status=_normalize_enum(target.status, TargetStatus),
                    target_meta=target.target_meta,
                    uploaded_at=target.uploaded_at,
                )
            )

        # Сохранение этапов обработки
        for stage in recording.processing_stages:
            session.add(
                ProcessingStageModel(
                    recording_id=db_recording.id,
                    stage_type=_normalize_enum(stage.stage_type, ProcessingStageType),
                    status=_normalize_enum(stage.status, ProcessingStageStatus),
                    failed=stage.failed,
                    failed_at=stage.failed_at,
                    failed_reason=stage.failed_reason,
                    retry_count=stage.retry_count,
                    stage_meta=stage.stage_meta,
                    completed_at=stage.completed_at,
                )
            )

    async def get_recordings(self, status: ProcessingStatus | None = None) -> list[MeetingRecording]:
        """Получение записей из базы данных."""
        async with self.async_session() as session:
            try:
                query = select(RecordingModel).options(
                    selectinload(RecordingModel.source),
                    selectinload(RecordingModel.outputs),
                    selectinload(RecordingModel.processing_stages),
                    selectinload(RecordingModel.processing_stages),
                )
                if status:
                    query = query.where(RecordingModel.status == status)
                query = query.order_by(RecordingModel.start_time.desc())

                result = await session.execute(query)
                db_recordings = result.scalars().all()

                recordings = []
                for db_recording in db_recordings:
                    recording = self._convert_db_to_model(db_recording)
                    recordings.append(recording)

                logger.debug(
                    f"Получено записей из БД: count={len(recordings)} | status={status.value if status else 'all'}"
                )
                return recordings

            except Exception as e:
                logger.error(f"Ошибка получения записей: status={status.value if status else 'all'} | error={e}")
                return []

    async def get_recordings_by_ids(self, recording_ids: list[int]) -> list[MeetingRecording]:
        """Получение записей по ID."""
        async with self.async_session() as session:
            try:
                query = (
                    select(RecordingModel)
                    .options(
                        selectinload(RecordingModel.source),
                        selectinload(RecordingModel.outputs),
                    )
                    .where(RecordingModel.id.in_(recording_ids))
                )
                result = await session.execute(query)
                db_recordings = result.scalars().all()

                recordings = []
                for db_recording in db_recordings:
                    recording = self._convert_db_to_model(db_recording)
                    recordings.append(recording)

                logger.debug(f"Получено записей по ID: count={len(recordings)} | requested={len(recording_ids)}")
                return recordings

            except Exception as e:
                logger.error(f"Ошибка получения записей по ID: recording_ids={recording_ids} | error={e}")
                return []

    async def get_records_older_than(self, cutoff_date: datetime) -> list[MeetingRecording]:
        """Получение записей, которые последний раз обновлялись раньше указанной даты (исключая EXPIRED)"""
        async with self.async_session() as session:
            try:
                query = (
                    select(RecordingModel)
                    .options(
                        selectinload(RecordingModel.source),
                        selectinload(RecordingModel.outputs),
                    )
                    .where(
                        RecordingModel.updated_at < cutoff_date,
                        RecordingModel.status != ProcessingStatus.EXPIRED,
                    )
                )
                result = await session.execute(query)
                db_recordings = result.scalars().all()

                recordings = []
                for db_recording in db_recordings:
                    recording = self._convert_db_to_model(db_recording)
                    recordings.append(recording)

                logger.debug(f"Получено старых записей: count={len(recordings)} | cutoff_date={cutoff_date}")
                return recordings

            except Exception as e:
                logger.error(f"Ошибка получения старых записей: cutoff_date={cutoff_date} | error={e}")
                return []

    async def update_recording(self, recording: MeetingRecording):
        """Обновление записи в базе данных."""
        async with self.async_session() as session:
            try:
                db_recording = await session.get(
                    RecordingModel,
                    recording.db_id,
                    options=[
                        selectinload(RecordingModel.source),
                        selectinload(RecordingModel.outputs),
                        selectinload(RecordingModel.processing_stages),
                    ],
                )
                if not db_recording:
                    logger.error(f"Запись не найдена: recording_id={recording.db_id}")
                    return

                await self._update_existing_recording(session, db_recording, recording)

                await session.commit()

                logger.debug(f"Запись обновлена: recording={recording.display_name} | recording_id={recording.db_id}")

            except Exception as e:
                await session.rollback()
                logger.error(
                    f"Ошибка обновления записи: recording={recording.display_name} | recording_id={recording.db_id} | error={e}"
                )
                raise

    def _convert_db_to_model(self, db_recording: RecordingModel) -> MeetingRecording:
        """Преобразование записи из БД в модель."""
        # Конвертируем datetime из БД в формат Zoom API (2021-03-18T05:41:36Z)
        if isinstance(db_recording.start_time, datetime):
            dt = db_recording.start_time
            # Конвертируем в UTC (PostgreSQL хранит в UTC, но может вернуть в timezone сессии)
            if dt.tzinfo is not None:
                dt_utc = dt.astimezone(ZoneInfo("UTC"))
            else:
                # Если timezone нет, считаем что это UTC
                dt_utc = dt.replace(tzinfo=ZoneInfo("UTC"))

            # Форматируем в формат Zoom API (с 'Z' в конце)
            start_time_str = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            # Если это не datetime (не должно быть), преобразуем в строку
            start_time_str = str(db_recording.start_time)

        source_type_raw = db_recording.source.source_type if db_recording.source else SourceType.ZOOM
        source_type = _normalize_enum(source_type_raw, SourceType)
        source_key = db_recording.source.source_key if db_recording.source else ""
        source_meta = (db_recording.source.meta if db_recording.source and db_recording.source.meta else {}) or {}

        outputs: list[OutputTarget] = []
        for out in db_recording.outputs:
            out_type = _normalize_enum(out.target_type, TargetType)
            out_status = _normalize_enum(out.status, TargetStatus)
            outputs.append(
                OutputTarget(
                    target_type=out_type,
                    status=out_status,
                    target_meta=out.target_meta,
                    uploaded_at=out.uploaded_at,
                )
            )

        # Конвертация этапов обработки
        processing_stages: list[ProcessingStage] = []
        for stage in db_recording.processing_stages:
            stage_type = _normalize_enum(stage.stage_type, ProcessingStageType)
            stage_status = _normalize_enum(stage.status, ProcessingStageStatus)
            processing_stages.append(
                ProcessingStage(
                    stage_type=stage_type,
                    status=stage_status,
                    failed=stage.failed,
                    failed_at=stage.failed_at,
                    failed_reason=stage.failed_reason,
                    retry_count=stage.retry_count,
                    stage_meta=stage.stage_meta,
                    completed_at=stage.completed_at,
                )
            )

        meeting_data = {
            "user_id": db_recording.user_id,
            "display_name": db_recording.display_name,
            "start_time": start_time_str,
            "duration": db_recording.duration,
            "status": db_recording.status,
            "is_mapped": db_recording.is_mapped,
            "expire_at": db_recording.expire_at,
            "source_type": source_type,
            "source_key": source_key,
            "source_metadata": source_meta,
            "local_video_path": db_recording.local_video_path,
            "processed_video_path": db_recording.processed_video_path,
            "processed_audio_dir": db_recording.processed_audio_dir,
            "transcription_dir": db_recording.transcription_dir,
            "video_file_size": db_recording.video_file_size,
            "transcription_info": db_recording.transcription_info,
            "topic_timestamps": db_recording.topic_timestamps,
            "main_topics": db_recording.main_topics,
            "processing_preferences": db_recording.processing_preferences,
            "downloaded_at": db_recording.downloaded_at,
            "output_targets": outputs,
            "processing_stages": processing_stages,
            "failed": db_recording.failed,
            "failed_at": db_recording.failed_at,
            "failed_reason": db_recording.failed_reason,
            "failed_at_stage": db_recording.failed_at_stage,
            "retry_count": db_recording.retry_count,
        }

        # Zoom-совместимые поля из метаданных
        if source_meta:
            meeting_data["id"] = source_meta.get("meeting_id", "")
            meeting_data["account"] = source_meta.get("account", "default")

            # Ссылки для скачивания (с поддержкой старого и нового формата)
            meeting_data["video_file_download_url"] = source_meta.get("download_url") or source_meta.get("video_file_download_url")
            meeting_data["download_access_token"] = source_meta.get("download_access_token")

            # Пароли и доступ
            meeting_data["password"] = source_meta.get("password")
            meeting_data["recording_play_passcode"] = source_meta.get("recording_play_passcode")

            # Мульти-part записи
            meeting_data["part_index"] = source_meta.get("part_index")
            meeting_data["total_visible_parts"] = source_meta.get("total_visible_parts")

        recording = MeetingRecording(meeting_data)
        recording.db_id = db_recording.id
        return recording

    async def reset_recordings(self, keep_uploaded: bool = True) -> dict:
        """Сброс всех записей к статусу INITIALIZED (кроме загруженных).

        Args:
            keep_uploaded: Если True, не сбрасывать записи со статусом UPLOADED

        Returns:
            Словарь с результатами сброса
        """
        reset_count = 0
        by_status = {}

        async with self.async_session() as session:
            try:
                result = await session.execute(
                    select(RecordingModel).options(
                        selectinload(RecordingModel.source),
                        selectinload(RecordingModel.outputs),
                    )
                )
                db_recordings = result.scalars().unique().all()

                # Удаляем файлы и сбрасываем записи
                for db_recording in db_recordings:
                    # Если нужно оставить загруженные записи – проверяем наличие uploaded таргетов
                    if keep_uploaded:
                        uploaded_exists = any(
                            _normalize_enum(t.status, TargetStatus) == TargetStatus.UPLOADED
                            for t in db_recording.outputs
                        )
                        if uploaded_exists:
                            continue

                    # Удаляем физические файлы
                    if db_recording.local_video_path and os.path.exists(db_recording.local_video_path):
                        try:
                            os.remove(db_recording.local_video_path)
                            logger.debug(
                                f"Удален файл: path={db_recording.local_video_path} | recording_id={db_recording.id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Не удалось удалить файл: path={db_recording.local_video_path} | recording_id={db_recording.id} | error={e}"
                            )

                    if db_recording.processed_video_path and os.path.exists(db_recording.processed_video_path):
                        try:
                            os.remove(db_recording.processed_video_path)
                            logger.debug(
                                f"Удален файл: path={db_recording.processed_video_path} | recording_id={db_recording.id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Не удалось удалить файл: path={db_recording.processed_video_path} | recording_id={db_recording.id} | error={e}"
                            )

                    if db_recording.processed_audio_dir and os.path.exists(db_recording.processed_audio_dir):
                        try:
                            shutil.rmtree(db_recording.processed_audio_dir)
                            logger.debug(
                                f"Удалена папка аудио: path={db_recording.processed_audio_dir} | recording_id={db_recording.id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Не удалось удалить аудио директорию: path={db_recording.processed_audio_dir} | recording_id={db_recording.id} | error={e}"
                            )

                    if db_recording.transcription_dir and os.path.exists(db_recording.transcription_dir):
                        try:
                            shutil.rmtree(db_recording.transcription_dir)
                            logger.debug(
                                f"Удалена папка транскрипции: path={db_recording.transcription_dir} | recording_id={db_recording.id}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Не удалось удалить папку транскрипции: path={db_recording.transcription_dir} | recording_id={db_recording.id} | error={e}"
                            )

                    # Подсчитываем по статусам
                    old_status = (
                        db_recording.status.value if hasattr(db_recording.status, "value") else str(db_recording.status)
                    )
                    by_status[old_status] = by_status.get(old_status, 0) + 1

                    # Сбрасываем запись
                    if db_recording.is_mapped:
                        db_recording.status = ProcessingStatus.INITIALIZED
                    else:
                        db_recording.status = ProcessingStatus.SKIPPED

                    db_recording.local_video_path = None
                    db_recording.processed_video_path = None
                    db_recording.processed_audio_dir = None
                    db_recording.downloaded_at = None

                    # Сбрасываем транскрипцию и темы
                    db_recording.transcription_dir = None
                    db_recording.transcription_info = None
                    db_recording.topic_timestamps = None
                    db_recording.main_topics = None

                    # Сбрасываем статусы таргетов
                    for target in db_recording.outputs:
                        target.status = TargetStatus.NOT_UPLOADED
                        target.target_meta = None
                        target.uploaded_at = None

                    db_recording.updated_at = datetime.now()

                    reset_count += 1

                await session.commit()
                logger.info(
                    f"Сброшено записей: count={reset_count} | by_status={by_status} | keep_uploaded={keep_uploaded}"
                )

                return {
                    "total_reset": reset_count,
                    "by_status": by_status,
                }

            except Exception as e:
                await session.rollback()
                logger.error(f"Ошибка сброса записей: keep_uploaded={keep_uploaded} | error={e}")
                raise

    # ==================== User Management ====================

    async def get_user_by_id(self, user_id: int):
        """Получить пользователя по ID."""
        async with self.async_session() as session:
            from database.auth_models import UserModel

            result = await session.execute(select(UserModel).where(UserModel.id == user_id))
            return result.scalars().first()

    async def get_user_by_email(self, email: str):
        """Получить пользователя по email."""
        async with self.async_session() as session:
            from database.auth_models import UserModel

            result = await session.execute(select(UserModel).where(UserModel.email == email))
            return result.scalars().first()

    async def create_user(self, email: str, hashed_password: str, full_name: str | None = None):
        """Создать нового пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserModel

            user = UserModel(email=email, hashed_password=hashed_password, full_name=full_name)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def update_user(self, user_id: int, updates: dict):
        """Обновить пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserModel

            result = await session.execute(select(UserModel).where(UserModel.id == user_id))
            user = result.scalars().first()
            if not user:
                return None

            for key, value in updates.items():
                setattr(user, key, value)

            await session.commit()
            await session.refresh(user)
            return user

    # ==================== Refresh Tokens ====================

    async def create_refresh_token(self, user_id: int, token: str, expires_at: datetime):
        """Создать refresh токен."""
        async with self.async_session() as session:
            from database.auth_models import RefreshTokenModel

            refresh_token = RefreshTokenModel(user_id=user_id, token=token, expires_at=expires_at)
            session.add(refresh_token)
            await session.commit()
            await session.refresh(refresh_token)
            return refresh_token

    async def get_refresh_token(self, token: str):
        """Получить refresh токен."""
        async with self.async_session() as session:
            from database.auth_models import RefreshTokenModel

            result = await session.execute(select(RefreshTokenModel).where(RefreshTokenModel.token == token))
            return result.scalars().first()

    async def revoke_refresh_token(self, token: str):
        """Отозвать refresh токен."""
        async with self.async_session() as session:
            from database.auth_models import RefreshTokenModel

            result = await session.execute(select(RefreshTokenModel).where(RefreshTokenModel.token == token))
            refresh_token = result.scalars().first()
            if refresh_token:
                refresh_token.is_revoked = True
                await session.commit()
            return refresh_token

    # ==================== User Quotas ====================

    async def create_user_quota(
        self,
        user_id: int,
        max_recordings_per_month: int,
        max_storage_gb: int,
        max_concurrent_tasks: int,
    ):
        """Создать квоты для пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserQuotaModel

            quota = UserQuotaModel(
                user_id=user_id,
                max_recordings_per_month=max_recordings_per_month,
                max_storage_gb=max_storage_gb,
                max_concurrent_tasks=max_concurrent_tasks,
                quota_reset_at=datetime.utcnow() + __import__("datetime").timedelta(days=30),
            )
            session.add(quota)
            await session.commit()
            await session.refresh(quota)
            return quota

    async def get_user_quota(self, user_id: int):
        """Получить квоты пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserQuotaModel

            result = await session.execute(select(UserQuotaModel).where(UserQuotaModel.user_id == user_id))
            return result.scalars().first()

    async def update_user_quota(self, user_id: int, updates: dict):
        """Обновить квоты пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserQuotaModel

            result = await session.execute(select(UserQuotaModel).where(UserQuotaModel.user_id == user_id))
            quota = result.scalars().first()
            if not quota:
                return None

            for key, value in updates.items():
                setattr(quota, key, value)

            await session.commit()
            await session.refresh(quota)
            return quota

    # ==================== User Credentials ====================

    async def create_user_credential(self, user_id: int, platform: str, encrypted_data: str):
        """Создать учетные данные пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserCredentialModel

            credential = UserCredentialModel(user_id=user_id, platform=platform, encrypted_data=encrypted_data)
            session.add(credential)
            await session.commit()
            await session.refresh(credential)
            return credential

    async def get_user_credentials(self, user_id: int, platform: str):
        """Получить учетные данные пользователя для платформы."""
        async with self.async_session() as session:
            from database.auth_models import UserCredentialModel

            result = await session.execute(
                select(UserCredentialModel).where(
                    UserCredentialModel.user_id == user_id,
                    UserCredentialModel.platform == platform,
                    UserCredentialModel.is_active.is_(True),
                )
            )
            return result.scalars().first()

    async def update_user_credential(self, credential_id: int, encrypted_data: str):
        """Обновить учетные данные пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserCredentialModel

            result = await session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
            credential = result.scalars().first()
            if not credential:
                return None

            credential.encrypted_data = encrypted_data
            credential.last_used_at = datetime.utcnow()
            await session.commit()
            await session.refresh(credential)
            return credential

    async def delete_user_credential(self, credential_id: int):
        """Удалить учетные данные пользователя."""
        async with self.async_session() as session:
            from database.auth_models import UserCredentialModel

            result = await session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
            credential = result.scalars().first()
            if credential:
                await session.delete(credential)
                await session.commit()
            return credential

    async def close(self):
        """Закрытие соединения с базой данных."""
        if hasattr(self, "engine") and self.engine is not None:
            await self.engine.dispose()
            logger.info("Соединение с БД закрыто")
