from datetime import datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from logger import get_logger
from models.recording import (
    MeetingRecording,
    OutputTarget,
    ProcessingStatus,
    SourceType,
    TargetStatus,
    TargetType,
)

from .config import DatabaseConfig
from .models import Base, OutputTargetModel, RecordingModel, SourceMetadataModel

logger = get_logger()


def _parse_start_time(start_time_str: str) -> datetime:
    """Парсинг строки start_time в datetime объект (формат Zoom: 2021-03-18T05:41:36Z)."""
    if not start_time_str:
        raise ValueError("start_time не может быть пустым")

    try:
        # Zoom всегда возвращает формат с 'Z' в конце (UTC)
        # Заменяем 'Z' на '+00:00' для правильного парсинга
        if start_time_str.endswith('Z'):
            time_str = start_time_str[:-1] + '+00:00'
        else:
            time_str = start_time_str

        dt = datetime.fromisoformat(time_str)
        # Убеждаемся, что timezone установлен (должен быть UTC)
        if dt.tzinfo is None:
            from zoneinfo import ZoneInfo
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt
    except Exception as e:
        logger.error(f"Ошибка парсинга start_time '{start_time_str}': {e}")
        raise ValueError(f"Не удалось распарсить start_time: {start_time_str}") from e


def _build_source_metadata_payload(recording: MeetingRecording) -> dict:
    """Формируем JSONB метаданных источника из модели."""
    meta = dict(recording.source_metadata or {})

    zoom_fields = {
        "meeting_id": getattr(recording, "meeting_id", None),
        "account": getattr(recording, "account", None),
        "video_file_download_url": getattr(recording, "video_file_download_url", None),
        "download_access_token": getattr(recording, "download_access_token", None),
        "password": getattr(recording, "password", None),
        "recording_play_passcode": getattr(recording, "recording_play_passcode", None),
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
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_database_if_not_exists(self):
        """Создание базы данных, если она не существует."""
        try:
            parsed = urlparse(self.config.url)

            conn = await asyncpg.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                database='postgres',
            )

            result = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", self.config.database
            )

            if not result:
                await conn.execute(f'CREATE DATABASE "{self.config.database}"')
                logger.info(f"✅ База данных '{self.config.database}' создана")

            await conn.close()

        except Exception as e:
            logger.error(f"❌ Ошибка создания базы данных: {e}")
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
                database='postgres',
            )

            # Проверяем, существует ли база данных
            db_exists = await conn.fetchval(
                "SELECT 1 FROM pg_database WHERE datname = $1", self.config.database
            )

            if db_exists:
                # Завершаем все активные соединения к целевой БД
                # Используем параметризованный запрос для безопасности
                try:
                    await conn.execute("""
                        SELECT pg_terminate_backend(pg_stat_activity.pid)
                        FROM pg_stat_activity
                        WHERE pg_stat_activity.datname = $1
                        AND pid <> pg_backend_pid()
                    """, self.config.database)
                except Exception as e:
                    # Игнорируем ошибки при завершении соединений
                    logger.warning(f"⚠️  Не удалось завершить все соединения: {e}")

                # Удаляем базу данных
                # Экранируем двойные кавычки для идентификатора
                db_name_quoted = self.config.database.replace('"', '""')
                await conn.execute(f'DROP DATABASE IF EXISTS "{db_name_quoted}"')
                logger.info(f"🗑️  База данных '{self.config.database}' удалена")

            # Создаем базу данных заново
            # Экранируем двойные кавычки для идентификатора
            db_name_quoted = self.config.database.replace('"', '""')
            await conn.execute(f'CREATE DATABASE "{db_name_quoted}"')
            logger.info(f"✅ База данных '{self.config.database}' создана")

            await conn.close()

            # Пересоздаем engine для новой БД
            self.engine = create_async_engine(self.config.url, echo=False)
            self.async_session = async_sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )

            # Создаем таблицы
            await self.create_tables()

            logger.info("✅ База данных полностью пересоздана")

        except Exception as e:
            logger.error(f"❌ Ошибка пересоздания базы данных: {e}")
            raise

    async def create_tables(self):
        """Создание таблиц в базе данных."""
        try:
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("✅ Таблицы созданы")
        except Exception as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")
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
                        logger.warning(f"⚠️ Запись уже существует: {recording.display_name} - {e}")
                        continue
                    except Exception as e:
                        logger.error(f"❌ Ошибка сохранения записи {recording.display_name}: {e}")
                        continue

                await session.commit()
                logger.info(f"✅ Сохранено записей: {saved_count}/{len(recordings)}")
                return saved_count

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Ошибка транзакции: {e}")
                raise

    async def _find_existing_recording(
        self, session: AsyncSession, recording: MeetingRecording
    ) -> RecordingModel | None:
        """Поиск существующей записи по (source_type, source_key, start_time)."""
        try:
            start_time = _parse_start_time(recording.start_time)
            source_type = (
                recording.source_type if isinstance(recording.source_type, SourceType) else SourceType(recording.source_type)
            )
            stmt = (
                select(RecordingModel)
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
            logger.error(f"Ошибка поиска существующей записи: {e}")
            return None

    async def _update_existing_recording(
        self, session: AsyncSession, existing: RecordingModel, recording: MeetingRecording
    ):
        """Обновление существующей записи."""
        existing.display_name = recording.display_name
        existing.duration = recording.duration
        existing.video_file_size = recording.video_file_size
        existing.is_mapped = recording.is_mapped if recording.is_mapped is not None else existing.is_mapped

        # Обновляем статус без излишних ограничений, чтобы фиксировать прогресс
        new_status = recording.status if isinstance(recording.status, ProcessingStatus) else ProcessingStatus(recording.status)
        if existing.status != new_status:
            existing.status = new_status
        existing.expire_at = recording.expire_at

        existing.local_video_path = recording.local_video_path
        existing.processed_video_path = recording.processed_video_path
        existing.processed_audio_dir = recording.processed_audio_dir
        existing.transcription_dir = recording.transcription_dir
        existing.transcription_info = recording.transcription_info
        existing.topic_timestamps = recording.topic_timestamps
        existing.main_topics = recording.main_topics
        existing.downloaded_at = recording.downloaded_at

        # Обновляем источник
        meta = _build_source_metadata_payload(recording)
        if existing.source is None:
            source = SourceMetadataModel(
                recording_id=existing.id,
                source_type=recording.source_type if isinstance(recording.source_type, SourceType) else SourceType(recording.source_type),
                source_key=recording.source_key,
                metadata=meta,
            )
            session.add(source)
        else:
            existing.source.source_type = (
                recording.source_type if isinstance(recording.source_type, SourceType) else SourceType(recording.source_type)
            )
            existing.source.source_key = recording.source_key
            existing.source.meta = meta

        # Синхронизация output targets
        existing_outputs: dict[TargetType, OutputTargetModel] = {}
        for out in existing.outputs:
            key = out.target_type if isinstance(out.target_type, TargetType) else TargetType(out.target_type)
            existing_outputs[key] = out

        for target in recording.output_targets:
            target_type_value = target.target_type if isinstance(target.target_type, TargetType) else TargetType(target.target_type)
            db_target = existing_outputs.get(target_type_value)
            target_status = target.status if isinstance(target.status, TargetStatus) else TargetStatus(target.status)
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
            downloaded_at=recording.downloaded_at,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        session.add(db_recording)
        await session.flush()
        recording.db_id = db_recording.id

        # Источник
        meta = _build_source_metadata_payload(recording)
        source_model = SourceMetadataModel(
            recording_id=db_recording.id,
            source_type=recording.source_type if isinstance(recording.source_type, SourceType) else SourceType(recording.source_type),
            source_key=recording.source_key,
            meta=meta,
        )
        session.add(source_model)
        await session.flush()

        # Выходы
        for target in recording.output_targets:
            session.add(
                OutputTargetModel(
                    recording_id=db_recording.id,
                    target_type=target.target_type if isinstance(target.target_type, TargetType) else TargetType(target.target_type),
                    status=target.status if isinstance(target.status, TargetStatus) else TargetStatus(target.status),
                    target_meta=target.target_meta,
                    uploaded_at=target.uploaded_at,
                )
            )

    async def get_recordings(
        self, status: ProcessingStatus | None = None
    ) -> list[MeetingRecording]:
        """Получение записей из базы данных."""
        async with self.async_session() as session:
            try:
                query = select(RecordingModel).options(
                    selectinload(RecordingModel.source),
                    selectinload(RecordingModel.outputs),
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

                logger.debug(f"📋 Получено записей из БД: {len(recordings)}")
                return recordings

            except Exception as e:
                logger.error(f"❌ Ошибка получения записей: {e}")
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

                logger.debug(f"📋 Получено записей по ID: {len(recordings)}")
                return recordings

            except Exception as e:
                logger.error(f"❌ Ошибка получения записей по ID: {e}")
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

                logger.debug(f"📋 Получено старых записей: {len(recordings)}")
                return recordings

            except Exception as e:
                logger.error(f"❌ Ошибка получения старых записей: {e}")
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
                    ],
                )
                if not db_recording:
                    logger.error(f"❌ Запись с ID {recording.db_id} не найдена")
                    return

                await self._update_existing_recording(session, db_recording, recording)

                await session.commit()

                logger.debug(f"✅ Запись {recording.display_name} обновлена в БД")

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Ошибка обновления записи {recording.display_name}: {e}")
                raise

    def _convert_db_to_model(self, db_recording: RecordingModel) -> MeetingRecording:
        """Преобразование записи из БД в модель."""
        # Конвертируем datetime из БД в формат Zoom API (2021-03-18T05:41:36Z)
        if isinstance(db_recording.start_time, datetime):
            from zoneinfo import ZoneInfo

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
        source_type = source_type_raw if isinstance(source_type_raw, SourceType) else SourceType(source_type_raw)
        source_key = db_recording.source.source_key if db_recording.source else ""
        source_meta = db_recording.source.meta if db_recording.source else {}

        outputs: list[OutputTarget] = []
        for out in db_recording.outputs:
            out_type = out.target_type if isinstance(out.target_type, TargetType) else TargetType(out.target_type)
            out_status = out.status if isinstance(out.status, TargetStatus) else TargetStatus(out.status)
            outputs.append(
                OutputTarget(
                    target_type=out_type,
                    status=out_status,
                    target_meta=out.target_meta,
                    uploaded_at=out.uploaded_at,
                )
            )

        meeting_data = {
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
            "downloaded_at": db_recording.downloaded_at,
            "output_targets": outputs,
        }

        # Zoom-совместимые поля из метаданных
        if source_meta:
            meeting_data["id"] = source_meta.get("meeting_id", "")
            meeting_data["account"] = source_meta.get("account", "default")
            meeting_data["video_file_download_url"] = source_meta.get("video_file_download_url")
            meeting_data["download_access_token"] = source_meta.get("download_access_token")
            meeting_data["password"] = source_meta.get("password")
            meeting_data["recording_play_passcode"] = source_meta.get("recording_play_passcode")

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
        import os

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
                            (t.status == TargetStatus.UPLOADED or (not isinstance(t.status, TargetStatus) and t.status == TargetStatus.UPLOADED.value))
                            for t in db_recording.outputs
                        )
                        if uploaded_exists:
                            continue

                    # Удаляем физические файлы
                    if db_recording.local_video_path and os.path.exists(db_recording.local_video_path):
                        try:
                            os.remove(db_recording.local_video_path)
                            logger.info(f"🗑️ Удален файл: {db_recording.local_video_path}")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось удалить файл {db_recording.local_video_path}: {e}")

                    if db_recording.processed_video_path and os.path.exists(db_recording.processed_video_path):
                        try:
                            os.remove(db_recording.processed_video_path)
                            logger.info(f"🗑️ Удален файл: {db_recording.processed_video_path}")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось удалить файл {db_recording.processed_video_path}: {e}")

                    if db_recording.processed_audio_dir and os.path.exists(db_recording.processed_audio_dir):
                        try:
                            import shutil
                            shutil.rmtree(db_recording.processed_audio_dir)
                            logger.info(f"🗑️ Удалена папка аудио: {db_recording.processed_audio_dir}")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось удалить аудио директорию {db_recording.processed_audio_dir}: {e}")

                    # Удаляем папку транскрипции, если она существует
                    if db_recording.transcription_dir and os.path.exists(db_recording.transcription_dir):
                        try:
                            import shutil
                            shutil.rmtree(db_recording.transcription_dir)
                            logger.info(f"🗑️ Удалена папка транскрипции: {db_recording.transcription_dir}")
                        except Exception as e:
                            logger.warning(f"⚠️ Не удалось удалить папку транскрипции {db_recording.transcription_dir}: {e}")

                    # Подсчитываем по статусам
                    old_status = db_recording.status.value if hasattr(db_recording.status, 'value') else str(db_recording.status)
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
                logger.info(f"✅ Сброшено записей: {reset_count}")

                return {
                    'total_reset': reset_count,
                    'by_status': by_status,
                }

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Ошибка сброса записей: {e}")
                raise

    async def close(self):
        """Закрытие соединения с базой данных."""
        if hasattr(self, 'engine') and self.engine is not None:
            await self.engine.dispose()
            logger.info("🔌 Соединение с БД закрыто")
