"""Сервис для работы с записями."""

from typing import Any

from api.repositories.recording_repo import RecordingRepository
from api.schemas.common.pagination import PaginationParams
from api.schemas.recording.request import ProcessRecordingRequest, UpdateRecordingRequest
from api.schemas.recording.response import RecordingListResponse, RecordingResponse
from api.shared.exceptions import APIException, NotFoundError

# Import Celery tasks
from api.tasks.processing import (
    batch_process_recordings,
    process_single_recording,
)
from api.tasks.processing import (
    generate_subtitles as generate_subtitles_task,
)
from api.tasks.upload import batch_upload_recordings as upload_to_platforms
from logger import get_logger
from models import MeetingRecording, ProcessingStatus
from pipeline_manager import PipelineManager

logger = get_logger()


class RecordingService:
    """Сервис для работы с записями.
    Является основным узлом бизнес-логики для API и CLI.
    """

    def __init__(
        self,
        repo: RecordingRepository,
        pipeline: PipelineManager,
    ):
        self.repo = repo
        self.pipeline = pipeline

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
        """Синхронизация записей из Zoom (даты уже обработаны в роутере)."""
        from config import load_config_from_file

        # Загружаем конфиги (в будущем — из настроек пользователя для multi-tenancy)
        configs = load_config_from_file("config/zoom_creds.json")

        count = await self.pipeline.sync_zoom_recordings(configs, from_date, to_date)
        return count

    async def process_recording(
        self,
        recording_id: int,
        request: ProcessRecordingRequest,
        use_celery: bool = True,
    ) -> dict[str, Any]:
        """
        Запуск обработки конкретной записи.

        Args:
            recording_id: ID записи
            request: Параметры обработки
            use_celery: Использовать Celery (True) или синхронную обработку (False)

        Returns:
            Словарь с task_id (если Celery) или статусом (если синхронно)
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
            if request.topic_mode:
                prefs["topic_mode"] = request.topic_mode

        # Обновляем модель
        recording.processing_preferences = prefs
        await self.repo.save(recording)

        if use_celery:
            # Запускаем через Celery (асинхронно)
            task = process_single_recording.apply_async(
                args=[recording_id],
                kwargs={
                    "enable_transcription": enable_transcription,
                    "enable_topics": prefs.get("enable_topics", True),
                    "enable_subtitles": prefs.get("enable_subtitles", True),
                    "transcription_model": request.transcription_model,
                    "topic_model": request.topic_model,
                    "topic_mode": request.topic_mode,
                },
                priority=7,  # Высокий приоритет для одиночных задач
            )

            return {
                "message": "Processing task scheduled",
                "recording_id": recording_id,
                "task_id": task.id,
                "status_url": f"/api/v1/tasks/{task.id}",
            }
        else:
            # Синхронная обработка (для CLI или отладки)
            try:
                await self.pipeline._process_single_video_complete(
                    recording,
                    platforms=request.platforms,
                    no_transcription=request.no_transcription,
                    transcription_model=request.transcription_model,
                    topic_mode=request.topic_mode,
                    topic_model=request.topic_model,
                )
                success = True
            except Exception as e:
                logger.error(f"Error processing recording {recording_id}: {e}")
                success = False

            if not success:
                raise APIException(status_code=500, detail="Failed to process recording")

            updated = await self.repo.find_by_id(recording_id)

            return {
                "message": "Processing completed",
                "recording_id": recording_id,
                "status": updated.status if updated else recording.status,
            }

    async def run_batch_processing(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        select_all: bool = False,
        recording_ids: list[int] | None = None,
        platforms: list[str] | None = None,
        no_transcription: bool = False,
        use_celery: bool = True,
    ) -> dict[str, Any]:
        """
        Запуск пакетной обработки.

        Args:
            from_date: Начальная дата
            to_date: Конечная дата
            select_all: Обработать все записи
            recording_ids: Список ID записей
            platforms: Платформы для загрузки
            no_transcription: Отключить транскрибацию
            use_celery: Использовать Celery (True) или синхронную обработку (False)

        Returns:
            Словарь с task_id (если Celery) или результатом (если синхронно)
        """
        # Определяем список записей для обработки
        if recording_ids:
            ids_to_process = recording_ids
        else:
            # Получаем записи по датам или все
            recordings = await self.repo.find_all()
            if from_date or to_date:
                from utils.data_processing import filter_recordings_by_date_range

                recordings = filter_recordings_by_date_range(recordings, from_date, to_date)
            ids_to_process = [r.id for r in recordings]

        if not ids_to_process:
            return {"message": "No recordings to process", "count": 0}

        if use_celery:
            # Запускаем через Celery (асинхронно)
            task = batch_process_recordings.apply_async(
                args=[ids_to_process],
                kwargs={
                    "enable_transcription": not no_transcription,
                    "enable_topics": True,
                    "enable_subtitles": True,
                },
                priority=5,  # Средний приоритет для пакетных задач
            )

            return {
                "message": "Batch processing scheduled",
                "task_id": task.id,
                "recordings_count": len(ids_to_process),
                "status_url": f"/api/v1/tasks/{task.id}",
            }
        else:
            # Синхронная обработка (для CLI)
            from config import load_config_from_file

            configs = load_config_from_file("config/zoom_creds.json")
            ids_str = [str(i) for i in ids_to_process]

            result = await self.pipeline.run_full_pipeline(
                configs=configs,
                from_date=from_date,
                to_date=to_date,
                select_all=select_all,
                recordings=ids_str,
                platforms=platforms or [],
                no_transcription=no_transcription,
            )
            return result

    async def generate_subtitles(
        self,
        recording_ids: list[int] | None = None,
        formats: list[str] | None = None,
        use_celery: bool = True,
    ) -> dict[str, Any]:
        """
        Генерация субтитров для указанных записей.

        Args:
            recording_ids: Список ID записей
            formats: Форматы субтитров
            use_celery: Использовать Celery (True) или синхронную обработку (False)

        Returns:
            Словарь с task_id (если Celery) или результатом (если синхронно)
        """
        if not recording_ids:
            return {"message": "No recordings specified", "count": 0}

        if use_celery:
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
        else:
            # Синхронная обработка (для CLI)
            recordings = await self.repo.db.get_recordings_by_ids(recording_ids)
            if not recordings:
                return {"message": "No recordings found", "count": 0}

            count = await self.pipeline.generate_subtitles(recordings, formats=formats)
            return {"message": "Subtitles generated", "count": count}

    async def upload_recordings(
        self,
        recording_ids: list[int],
        platforms: list[str],
        upload_captions: bool | None = None,
        use_celery: bool = True,
    ) -> dict[str, Any]:
        """
        Загрузка указанных записей на платформы.

        Args:
            recording_ids: Список ID записей
            platforms: Платформы для загрузки
            upload_captions: Загружать субтитры
            use_celery: Использовать Celery (True) или синхронную обработку (False)

        Returns:
            Словарь с task_id (если Celery) или результатом (если синхронно)
        """
        if not recording_ids:
            return {"message": "No recordings specified", "count": 0}

        if use_celery:
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
        else:
            # Синхронная обработка (для CLI)
            recordings = await self.repo.db.get_recordings_by_ids(recording_ids)
            if not recordings:
                return {"message": "No recordings found", "count": 0}

            count, uploaded = await self.pipeline.upload_recordings(
                recordings, platforms=platforms, upload_captions=upload_captions
            )
            return {
                "message": "Upload completed",
                "count": count,
                "uploaded": [r.id for r in uploaded],
            }

    async def clean_old_recordings(self, days_ago: int = 7) -> dict[str, Any]:
        """Очистка старых записей."""
        return await self.pipeline.clean_old_recordings(days_ago=days_ago)

    async def reset_recordings(self, recording_ids: list[int]) -> dict:
        """Сброс статусов записей."""
        return await self.pipeline.reset_specific_recordings(recording_ids)

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

    def _to_response(self, recording: MeetingRecording) -> RecordingResponse:
        """Конвертация MeetingRecording в RecordingResponse."""
        # ... существующая логика конвертации ...
        # (сохраняю для краткости, она корректна)

        # Конвертируем source
        source = None
        if recording.source_type:
            source = {
                "source_type": recording.source_type,
                "source_key": recording.source_key,
                "metadata": recording.source_metadata or {},
            }

        # Конвертируем outputs
        outputs = []
        for target in getattr(recording, "output_targets", []):
            outputs.append(
                {
                    "id": getattr(target, "id", 0),
                    "target_type": target.target_type,
                    "status": target.status,
                    "target_meta": target.target_meta or {},
                    "uploaded_at": getattr(target, "uploaded_at", None),
                }
            )

        # Конвертируем processing_stages
        stages = []
        for stage in getattr(recording, "processing_stages", []):
            stages.append(
                {
                    "stage_type": (
                        stage.stage_type.value if hasattr(stage.stage_type, "value") else str(stage.stage_type)
                    ),
                    "status": (stage.status.value if hasattr(stage.status, "value") else str(stage.status)),
                    "failed": stage.failed,
                    "failed_at": stage.failed_at,
                    "failed_reason": stage.failed_reason,
                    "retry_count": stage.retry_count,
                    "completed_at": getattr(stage, "completed_at", None),
                }
            )

        return RecordingResponse(
            id=recording.db_id or 0,
            display_name=recording.display_name,
            start_time=recording.start_time,
            duration=recording.duration,
            status=recording.status,
            is_mapped=recording.is_mapped,
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
