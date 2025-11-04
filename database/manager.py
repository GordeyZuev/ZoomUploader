
from datetime import datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from logger import get_logger
from models.recording import MeetingRecording, PlatformStatus, ProcessingStatus
from utils.formatting import normalize_datetime_string

from .config import DatabaseConfig
from .models import Base, RecordingModel

logger = get_logger()


def _parse_start_time(start_time_str: str) -> datetime:
    """Парсинг строки start_time в datetime объект."""
    if not start_time_str:
        raise ValueError("start_time не может быть пустым")

    try: # TODO fix
        normalized_time = normalize_datetime_string(start_time_str)
        dt = datetime.fromisoformat(normalized_time)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception as e:
        logger.error(f"Ошибка парсинга start_time '{start_time_str}': {e}")
        raise ValueError(f"Не удалось распарсить start_time: {start_time_str}") from e


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
                        logger.warning(f"⚠️ Запись уже существует: {recording.topic} - {e}")
                        continue
                    except Exception as e:
                        logger.error(f"❌ Ошибка сохранения записи {recording.topic}: {e}")
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
        """Поиск существующей записи по meeting_id и start_time"""
        try:
            start_time = _parse_start_time(recording.start_time)
            stmt = select(RecordingModel).where(
                RecordingModel.meeting_id == str(recording.meeting_id),
                RecordingModel.start_time == start_time,
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
        existing.topic = recording.topic
        existing.duration = recording.duration
        existing.video_file_size = recording.video_file_size
        existing.video_file_download_url = recording.video_file_download_url
        existing.download_access_token = recording.download_access_token
        existing.password = recording.password
        existing.recording_play_passcode = recording.recording_play_passcode
        existing.account = recording.account
        existing.meeting_id = str(recording.meeting_id)

        if existing.status == ProcessingStatus.INITIALIZED:
            existing.is_mapped = recording.is_mapped
            existing.status = recording.status
            logger.debug(
                f"Обновление записи {existing.id}: статус INITIALIZED -> is_mapped={recording.is_mapped}, status={recording.status.value}"
            )
        elif existing.status == ProcessingStatus.SKIPPED:
            if recording.status == ProcessingStatus.INITIALIZED:
                # Найден маппинг - обновляем статус
                logger.info(
                    f"🔄 Обновление записи {existing.id}: SKIPPED -> INITIALIZED (is_mapped: {existing.is_mapped} -> {recording.is_mapped})"
                )
                existing.is_mapped = recording.is_mapped
                existing.status = recording.status
            elif recording.is_mapped != existing.is_mapped:
                # Обновляем только is_mapped если изменился
                logger.debug(
                    f"Обновление записи {existing.id}: is_mapped {existing.is_mapped} -> {recording.is_mapped}"
                )
                existing.is_mapped = recording.is_mapped

        if existing.youtube_status != PlatformStatus.UPLOADED_YOUTUBE:
            existing.youtube_status = recording.youtube_status
        if existing.vk_status != PlatformStatus.UPLOADED_VK:
            existing.vk_status = recording.vk_status

        existing.updated_at = datetime.now()
        session.add(existing)

    async def _create_new_recording(self, session: AsyncSession, recording: MeetingRecording):
        """Создание новой записи."""
        db_recording = RecordingModel(
            topic=recording.topic,
            start_time=_parse_start_time(recording.start_time),
            duration=recording.duration,
            video_file_size=recording.video_file_size,
            video_file_download_url=recording.video_file_download_url,
            download_access_token=recording.download_access_token,
            password=recording.password,
            recording_play_passcode=recording.recording_play_passcode,
            account=recording.account,
            meeting_id=str(recording.meeting_id),
            is_mapped=recording.is_mapped,
            status=recording.status,
            local_video_path=recording.local_video_path,
            processed_video_path=recording.processed_video_path,
            downloaded_at=recording.downloaded_at,
            youtube_status=recording.youtube_status,
            youtube_url=recording.youtube_url,
            vk_status=recording.vk_status,
            vk_url=recording.vk_url,
            processing_notes=recording.processing_notes,
            processing_time=recording.processing_time,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        session.add(db_recording)
        await session.flush()
        recording.db_id = db_recording.id

    async def get_recordings(
        self, status: ProcessingStatus | None = None
    ) -> list[MeetingRecording]:
        """Получение записей из базы данных."""
        async with self.async_session() as session:
            try:
                query = select(RecordingModel)
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
                query = select(RecordingModel).where(RecordingModel.id.in_(recording_ids))
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
                query = select(RecordingModel).where(
                    RecordingModel.updated_at < cutoff_date,
                    RecordingModel.status != ProcessingStatus.EXPIRED,
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
                db_recording = await session.get(RecordingModel, recording.db_id)
                if not db_recording:
                    logger.error(f"❌ Запись с ID {recording.db_id} не найдена")
                    return

                db_recording.topic = recording.topic
                db_recording.duration = recording.duration
                db_recording.video_file_size = recording.video_file_size
                db_recording.video_file_download_url = recording.video_file_download_url
                db_recording.download_access_token = recording.download_access_token
                db_recording.password = recording.password
                db_recording.recording_play_passcode = recording.recording_play_passcode
                db_recording.account = recording.account
                db_recording.meeting_id = str(recording.meeting_id)
                db_recording.is_mapped = recording.is_mapped
                db_recording.status = recording.status
                db_recording.local_video_path = recording.local_video_path
                db_recording.processed_video_path = recording.processed_video_path
                db_recording.downloaded_at = recording.downloaded_at
                db_recording.youtube_status = recording.youtube_status
                db_recording.youtube_url = recording.youtube_url
                db_recording.vk_status = recording.vk_status
                db_recording.vk_url = recording.vk_url
                db_recording.processing_notes = recording.processing_notes
                db_recording.processing_time = recording.processing_time
                db_recording.updated_at = datetime.now()

                session.add(db_recording)
                await session.commit()

                logger.debug(f"✅ Запись {recording.topic} обновлена в БД")

            except Exception as e:
                await session.rollback()
                logger.error(f"❌ Ошибка обновления записи {recording.topic}: {e}")
                raise

    def _convert_db_to_model(self, db_recording: RecordingModel) -> MeetingRecording:
        """Преобразование записи из БД в модель."""
        meeting_data = {
            'topic': db_recording.topic,
            'start_time': db_recording.start_time.isoformat()
            if isinstance(db_recording.start_time, datetime)
            else str(db_recording.start_time),
            'duration': db_recording.duration,
            'id': db_recording.meeting_id,
            'account': db_recording.account,
            'recording_files': [],
        }

        recording = MeetingRecording(meeting_data)
        recording.db_id = db_recording.id
        recording.video_file_size = db_recording.video_file_size
        recording.video_file_download_url = db_recording.video_file_download_url
        recording.download_access_token = db_recording.download_access_token
        recording.password = db_recording.password
        recording.recording_play_passcode = db_recording.recording_play_passcode
        recording.is_mapped = db_recording.is_mapped
        recording.status = db_recording.status
        recording.local_video_path = db_recording.local_video_path
        recording.processed_video_path = db_recording.processed_video_path
        recording.downloaded_at = db_recording.downloaded_at
        recording.youtube_status = db_recording.youtube_status
        recording.youtube_url = db_recording.youtube_url
        recording.vk_status = db_recording.vk_status
        recording.vk_url = db_recording.vk_url
        recording.processing_notes = db_recording.processing_notes
        recording.processing_time = db_recording.processing_time

        return recording

    async def close(self):
        """Закрытие соединения с базой данных."""
        await self.engine.dispose()
        logger.info("🔌 Соединение с БД закрыто")
