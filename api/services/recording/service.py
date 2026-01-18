"""Recording service"""

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from api.repositories.recording_repo import RecordingRepository
from api.schemas.common.pagination import PaginationParams
from api.schemas.recording.request import ProcessRecordingRequest, UpdateRecordingRequest
from api.schemas.recording.response import RecordingListResponse, RecordingResponse
from api.shared.exceptions import NotFoundError
from api.tasks.processing import (
    generate_subtitles as generate_subtitles_task,
    process_single_recording,
)
from api.tasks.upload import batch_upload_recordings as upload_to_platforms
from api.zoom_api import ZoomAPI
from config.unified_config import AppConfig, load_app_config
from logger import get_logger
from models import MeetingRecording, ProcessingStatus
from utils import filter_available_recordings, get_recordings_by_date_range
from utils.title_mapper import TitleMapper

logger = get_logger()


class RecordingService:
    """Service for recording operations.

    Main business logic hub for the API.
    """

    def __init__(
        self,
        repo: RecordingRepository,
        app_config: AppConfig | None = None,
    ):
        self.repo = repo
        self.logger = get_logger()
        self.app_config = app_config or load_app_config()
        self.title_mapper = TitleMapper(self.app_config)

    async def list_recordings(
        self,
        status: ProcessingStatus | None = None,
        failed: bool | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        pagination: PaginationParams | None = None,
    ) -> RecordingListResponse:
        """Получение списка записей с расширенной фильтрацией."""
        pagination = pagination or PaginationParams()

        # Получаем все записи
        recordings = await self.repo.find_all(status=status, failed=failed)

        # Дополнительная фильтрация по датам (если нужно)
        if from_date or to_date:
            from utils.data_processing import filter_recordings_by_date_range

            recordings = filter_recordings_by_date_range(recordings, from_date, to_date)

        # Пагинация
        total = len(recordings)
        start = (pagination.page - 1) * pagination.per_page
        end = start + pagination.per_page
        paginated_recordings = recordings[start:end]

        # Конвертируем в схемы
        items = [self._to_response(r) for r in paginated_recordings]

        return RecordingListResponse(
            items=items,
            page=pagination.page,
            per_page=pagination.per_page,
            total=total,
            total_pages=((total + pagination.per_page - 1) // pagination.per_page if total > 0 else 1),
        )

    async def sync_zoom(
        self,
        from_date: str,
        to_date: str | None = None,
    ) -> int:
        """Sync recordings from Zoom API for the specified period."""
        from config import load_config_from_file

        # Load configs (future: from user settings for multi-tenancy)
        configs = load_config_from_file("config/zoom_creds.json")

        return await self._sync_zoom_recordings(configs, from_date, to_date)

    async def process_recording(
        self,
        recording_id: int,
        request: ProcessRecordingRequest,
    ) -> dict[str, Any]:
        """
        Запуск обработки конкретной записи через Celery.

        Args:
            recording_id: ID записи
            request: Параметры обработки

        Returns:
            Словарь с task_id
        """
        recording = await self.repo.find_by_id(recording_id)
        if not recording:
            raise NotFoundError("Recording", recording_id)

        # Применяем настройки из запроса
        prefs = recording.processing_preferences or {}
        enable_transcription = not request.no_transcription

        if request.no_transcription:
            prefs["enable_transcription"] = False
            prefs["enable_subtitles"] = False
        else:
            prefs["enable_transcription"] = True
            prefs["enable_subtitles"] = True
            prefs["enable_topics"] = True

            if request.transcription_model:
                prefs["transcription_model"] = request.transcription_model
            if request.topic_model:
                prefs["topic_model"] = request.topic_model
            if request.granularity:
                prefs["granularity"] = request.granularity

        # Обновляем модель
        recording.processing_preferences = prefs
        await self.repo.save(recording)

        task = process_single_recording.apply_async(
            args=[recording_id],
            kwargs={
                "enable_transcription": enable_transcription,
                "enable_topics": prefs.get("enable_topics", True),
                "enable_subtitles": prefs.get("enable_subtitles", True),
                "transcription_model": request.transcription_model,
                "topic_model": request.topic_model,
                "granularity": request.granularity,
            },
            priority=7,  # Высокий приоритет для одиночных задач
        )

        return {
            "message": "Processing task scheduled",
            "recording_id": recording_id,
            "task_id": task.id,
            "status_url": f"/api/v1/tasks/{task.id}",
        }

    async def generate_subtitles(
        self,
        recording_ids: list[int] | None = None,
        _formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Генерация субтитров для указанных записей через Celery.

        Args:
            recording_ids: Список ID записей
            formats: Форматы субтитров

        Returns:
            Словарь с task_id
        """
        if not recording_ids:
            return {"message": "No recordings specified", "count": 0}

        # Запускаем через Celery (асинхронно)
        task = generate_subtitles_task.apply_async(
            args=[recording_ids],
            priority=6,  # Высокий приоритет
        )

        return {
            "message": "Subtitle generation scheduled",
            "task_id": task.id,
            "recordings_count": len(recording_ids),
            "status_url": f"/api/v1/tasks/{task.id}",
        }

    async def upload_recordings(
        self,
        recording_ids: list[int],
        platforms: list[str],
        _upload_captions: bool | None = None,
    ) -> dict[str, Any]:
        """
        Загрузка указанных записей на платформы через Celery.

        Args:
            recording_ids: Список ID записей
            platforms: Платформы для загрузки
            upload_captions: Загружать субтитры

        Returns:
            Словарь с task_id
        """
        if not recording_ids:
            return {"message": "No recordings specified", "count": 0}

        # Запускаем через Celery (асинхронно)
        task = upload_to_platforms.apply_async(
            args=[recording_ids],
            kwargs={
                "youtube": "youtube" in platforms,
                "vk": "vk" in platforms,
            },
            priority=6,  # Высокий приоритет
        )

        return {
            "message": "Upload scheduled",
            "task_id": task.id,
            "recordings_count": len(recording_ids),
            "platforms": platforms,
            "status_url": f"/api/v1/tasks/{task.id}",
        }

    async def clean_old_recordings(self, days_ago: int = 7) -> dict[str, Any]:
        """Clean old recordings: delete files and set EXPIRED status."""
        cutoff_date = datetime.now() - timedelta(days=days_ago)
        all_recordings = await self.repo.get_older_than(cutoff_date)

        if not all_recordings:
            self.logger.info(f"No old recordings to clean: days_ago={days_ago}")
            return {"cleaned_count": 0, "freed_space_mb": 0, "cleaned_recordings": []}

        cleaned_count = 0
        freed_space_mb = 0
        cleaned_recordings = []

        for recording in all_recordings:
            file_deleted = False

            if recording.local_video_path and Path(recording.local_video_path).exists():
                try:
                    video_path = Path(recording.local_video_path)
                    file_size = video_path.stat().st_size / (1024 * 1024)
                    video_path.unlink()
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.debug(
                        f"Deleted file: path={recording.local_video_path} | size={file_size:.1f}MB | recording_id={recording.db_id}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error deleting file: path={recording.local_video_path} | recording_id={recording.db_id} | error={e}"
                    )

            if recording.processed_video_path and Path(recording.processed_video_path).exists():
                try:
                    video_path = Path(recording.processed_video_path)
                    file_size = video_path.stat().st_size / (1024 * 1024)
                    video_path.unlink()
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.debug(
                        f"Deleted file: path={recording.processed_video_path} | size={file_size:.1f}MB | recording_id={recording.db_id}"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Error deleting file: path={recording.processed_video_path} | recording_id={recording.db_id} | error={e}"
                    )

            if recording.processed_audio_path and Path(recording.processed_audio_path).exists():
                try:
                    audio_file = Path(recording.processed_audio_path)
                    file_size = audio_file.stat().st_size / (1024 * 1024)
                    audio_file.unlink()
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.debug(
                        f"Deleted audio: path={recording.processed_audio_path} | size={file_size:.1f}MB | recording_id={recording.db_id}"
                    )
                    # Remove directory if empty
                    audio_dir = audio_file.parent
                    if audio_dir.exists() and not any(audio_dir.iterdir()):
                        audio_dir.rmdir()
                        self.logger.debug(f"Removed empty directory: {audio_dir}")
                except Exception as e:
                    self.logger.error(
                        f"Error deleting audio: path={recording.processed_audio_path} | recording_id={recording.db_id} | error={e}"
                    )

            if file_deleted:
                recording.status = ProcessingStatus.EXPIRED
                await self.repo.save(recording)
                cleaned_count += 1
                cleaned_recordings.append(
                    {"id": recording.db_id, "display_name": recording.display_name, "deleted_files": []}
                )

        self.logger.info(
            f"Cleaned recordings: count={cleaned_count} | freed_space={freed_space_mb:.1f}MB | days_ago={days_ago}"
        )
        return {
            "cleaned_count": cleaned_count,
            "freed_space_mb": freed_space_mb,
            "cleaned_recordings": cleaned_recordings,
        }

    async def reset_recordings(self, recording_ids: list[int]) -> dict:
        """Reset recordings to INITIALIZED status."""
        reset_count = 0
        total_deleted_files = 0

        recordings = await self.repo.find_by_ids(recording_ids)
        recordings_by_id = {recording.db_id: recording for recording in recordings}

        for recording_id in recording_ids:
            try:
                recording = recordings_by_id.get(recording_id)
                if not recording:
                    self.logger.warning(f"Recording not found: recording_id={recording_id}")
                    continue

                deleted_files = []
                if recording.local_video_path and Path(recording.local_video_path).exists():
                    try:
                        Path(recording.local_video_path).unlink()
                        deleted_files.append(recording.local_video_path)
                        self.logger.debug(f"Deleted file: {recording.local_video_path} | recording_id={recording_id}")
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to delete file: {recording.local_video_path} | recording_id={recording_id} | error={e}"
                        )

                if recording.processed_video_path and Path(recording.processed_video_path).exists():
                    try:
                        Path(recording.processed_video_path).unlink()
                        deleted_files.append(recording.processed_video_path)
                        self.logger.debug(
                            f"Deleted file: {recording.processed_video_path} | recording_id={recording_id}"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to delete file: {recording.processed_video_path} | recording_id={recording_id} | error={e}"
                        )

                if recording.processed_audio_path and Path(recording.processed_audio_path).exists():
                    try:
                        audio_file = Path(recording.processed_audio_path)
                        audio_file.unlink()
                        deleted_files.append(recording.processed_audio_path)
                        self.logger.debug(
                            f"Deleted audio: {recording.processed_audio_path} | recording_id={recording_id}"
                        )
                        # Remove directory if empty
                        audio_dir = audio_file.parent
                        if audio_dir.exists() and not any(audio_dir.iterdir()):
                            audio_dir.rmdir()
                            self.logger.debug(f"Removed empty directory: {audio_dir}")
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to delete audio: {recording.processed_audio_path} | recording_id={recording_id} | error={e}"
                        )

                if recording.transcription_dir and Path(recording.transcription_dir).exists():
                    try:
                        shutil.rmtree(recording.transcription_dir)
                        deleted_files.append(recording.transcription_dir)
                        self.logger.debug(
                            f"Deleted transcription dir: {recording.transcription_dir} | recording_id={recording_id}"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"Failed to delete transcription dir: {recording.transcription_dir} | recording_id={recording_id} | error={e}"
                        )

                if recording.is_mapped:
                    recording.status = ProcessingStatus.INITIALIZED
                else:
                    recording.status = ProcessingStatus.SKIPPED

                recording.local_video_path = None
                recording.processed_video_path = None
                recording.processed_audio_path = None
                recording.downloaded_at = None

                recording.transcription_dir = None
                recording.transcription_info = None
                recording.topic_timestamps = None
                recording.main_topics = None

                recording.updated_at = datetime.now()

                await self.repo.save(recording)
                reset_count += 1
                total_deleted_files += len(deleted_files)

            except Exception as e:
                self.logger.error(f"Error resetting recording: recording_id={recording_id} | error={e}")

        return {
            "total_reset": reset_count,
            "by_status": {"INITIALIZED": reset_count},
            "deleted_files": total_deleted_files,
        }

    async def update_recording(
        self,
        recording_id: int,
        request: UpdateRecordingRequest,
    ) -> RecordingResponse:
        """Обновление записи."""
        recording = await self.repo.find_by_id(recording_id)
        if not recording:
            raise NotFoundError("Recording", recording_id)

        # Обновляем настройки обработки
        if request.processing_preferences:
            prefs_dict = request.processing_preferences.model_dump(exclude_unset=True)
            existing_prefs = recording.processing_preferences or {}
            existing_prefs.update(prefs_dict)
            recording.processing_preferences = existing_prefs
            await self.repo.save(recording)

        return self._to_response(recording)

    async def _sync_zoom_recordings(self, configs: dict, from_date: str, to_date: str | None = None) -> int:
        """Sync recordings from Zoom API to database for the specified period."""
        self.logger.info(f"📥 Syncing Zoom recordings for period {from_date} - {to_date or 'current date'}...")
        all_recordings = []

        for account, config in configs.items():
            self.logger.info(f"📥 Fetching recordings from account: {account}")

            try:
                api = ZoomAPI(config)
                recordings = await get_recordings_by_date_range(
                    api, start_date=from_date, end_date=to_date, filter_video_only=False
                )

                if recordings:
                    self.logger.info(f"   Found recordings: {len(recordings)}")
                    # Add account info to each recording
                    for recording in recordings:
                        recording.account = account
                    all_recordings.extend(recordings)
                else:
                    self.logger.info("   No recordings found")

            except Exception as e:
                self.logger.error(f"   ❌ Error fetching recordings from {account}: {e}")
                continue

        # Sync all recordings to DB (including deduplication)
        synced_count = 0
        if all_recordings:
            synced_count = await self._sync_recordings_to_db(all_recordings)

        updated_skipped_count = await self._check_and_update_skipped_recordings(from_date, to_date)

        total_count = synced_count + updated_skipped_count
        if total_count > 0:
            return total_count
        self.logger.info("📋 No recordings found")
        return 0

    async def _sync_recordings_to_db(self, recordings: list[MeetingRecording]) -> int:
        """Sync recordings to database."""
        if not recordings:
            return 0

        filtered_recordings = filter_available_recordings(recordings, min_duration_minutes=25, min_size_mb=30)
        filtered_count = len(recordings) - len(filtered_recordings)

        if filtered_count > 0:
            self.logger.info(f"Filtered recordings: {filtered_count} (do not meet criteria)")

        for recording in filtered_recordings:
            self._check_and_set_mapping(recording)

        synced_count = await self.repo.save_batch(filtered_recordings)
        self.logger.info(f"Synced recordings: {synced_count}/{len(filtered_recordings)}")
        return synced_count

    def _check_and_set_mapping(self, recording: MeetingRecording) -> None:
        """Check recording mapping and set appropriate status."""
        try:
            topic = recording.display_name.strip() if recording.display_name else ""
            mapping_result = self.title_mapper.map_title(topic, recording.start_time, recording.duration)

            if mapping_result.title:
                recording.is_mapped = True
                recording.status = ProcessingStatus.INITIALIZED
                self.logger.debug(
                    f"Mapping found: original='{topic}' | mapped='{mapping_result.title}' | recording_id={recording.db_id}"
                )
            else:
                recording.is_mapped = False
                recording.status = ProcessingStatus.SKIPPED
                self.logger.debug(f"Mapping not found: topic='{topic}' | recording_id={recording.db_id}")

        except Exception as e:
            recording.is_mapped = False
            recording.status = ProcessingStatus.SKIPPED
            self.logger.warning(
                f"Error checking mapping: recording={recording.display_name} | recording_id={recording.db_id} | error={e}"
            )

    async def _check_and_update_skipped_recordings(self, from_date: str, to_date: str | None = None) -> int:
        """Check existing SKIPPED recordings and update status if mapping appeared."""
        from utils.data_processing import filter_recordings_by_date_range

        skipped_recordings = await self.repo.find_all(status=ProcessingStatus.SKIPPED)

        if not skipped_recordings:
            return 0

        filtered_skipped = filter_recordings_by_date_range(skipped_recordings, from_date, to_date)

        if not filtered_skipped:
            return 0

        self.logger.info(
            f"Checking skipped recordings: count={len(filtered_skipped)} | period={from_date} - {to_date or 'current date'}"
        )

        updated_count = 0
        recordings_to_update = []

        for recording in filtered_skipped:
            old_status = recording.status
            old_is_mapped = recording.is_mapped
            topic = recording.display_name.strip() if recording.display_name else "No title"

            self.logger.debug(
                f"Checking recording: recording='{topic}' | recording_id={recording.db_id} | status={old_status.value} | is_mapped={old_is_mapped}"
            )

            self._check_and_set_mapping(recording)

            if old_status == ProcessingStatus.SKIPPED and recording.status == ProcessingStatus.INITIALIZED:
                self.logger.info(
                    f"Found mapping for skipped recording: recording='{topic}' | recording_id={recording.db_id} | status=INITIALIZED | is_mapped={recording.is_mapped}"
                )
                recordings_to_update.append(recording)
                updated_count += 1
            elif old_is_mapped != recording.is_mapped:
                self.logger.info(
                    f"Changed is_mapped: recording='{topic}' | recording_id={recording.db_id} | is_mapped={old_is_mapped} -> {recording.is_mapped}"
                )
                recordings_to_update.append(recording)
                updated_count += 1

        if recordings_to_update:
            await self.repo.save_batch(recordings_to_update)
            self.logger.info(f"Updated skipped recordings: {updated_count}/{len(filtered_skipped)}")

        return updated_count

    def _to_response(self, recording: MeetingRecording) -> RecordingResponse:
        """Конвертация MeetingRecording в RecordingResponse."""
        from api.schemas.recording.response import (
            OutputTargetResponse,
            ProcessingStageResponse,
            SourceResponse,
        )

        # Конвертируем source
        source = None
        if recording.source_type:
            source = SourceResponse(
                source_type=recording.source_type,
                source_key=recording.source_key,
                metadata=recording.source_metadata or {},
            )

        # Конвертируем outputs
        outputs = []
        for target in getattr(recording, "output_targets", []):
            outputs.append(
                OutputTargetResponse(
                    id=getattr(target, "id", 0),
                    target_type=target.target_type,
                    status=target.status,
                    target_meta=target.target_meta or {},
                    uploaded_at=getattr(target, "uploaded_at", None),
                )
            )

        # Конвертируем processing_stages
        stages = []
        for stage in getattr(recording, "processing_stages", []):
            stages.append(
                ProcessingStageResponse(
                    stage_type=(
                        stage.stage_type.value if hasattr(stage.stage_type, "value") else str(stage.stage_type)
                    ),
                    status=(stage.status.value if hasattr(stage.status, "value") else str(stage.status)),
                    failed=stage.failed,
                    failed_at=stage.failed_at,
                    failed_reason=stage.failed_reason,
                    retry_count=stage.retry_count,
                    completed_at=getattr(stage, "completed_at", None),
                )
            )

        return RecordingResponse(
            id=recording.db_id or 0,
            display_name=recording.display_name,
            start_time=recording.start_time,
            duration=recording.duration,
            status=recording.status,
            is_mapped=recording.is_mapped,
            blank_record=getattr(recording, "blank_record", False),
            processing_preferences=recording.processing_preferences,
            source=source,
            outputs=outputs,
            processing_stages=stages,
            failed=recording.failed,
            failed_at=recording.failed_at,
            failed_reason=recording.failed_reason,
            failed_at_stage=recording.failed_at_stage,
            video_file_size=recording.video_file_size,
            created_at=getattr(recording, "created_at", None) or recording.start_time,
            updated_at=getattr(recording, "updated_at", None) or recording.start_time,
        )
