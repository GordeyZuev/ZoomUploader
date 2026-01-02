"""Задачи для обработки записей (транскрибация, субтитры, темы)."""

from celery import Task
from celery.exceptions import SoftTimeLimitExceeded

from api.celery_app import celery_app
from database.manager import DatabaseManager
from logger import logger
from pipeline_manager import PipelineManager


class RecordingProcessingTask(Task):
    """Базовый класс для задач обработки записей."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Обработка ошибки задачи."""
        logger.error(f"Task {task_id} failed: {exc}")
        recording_id = args[0] if args else kwargs.get("recording_id")
        if recording_id:
            db = DatabaseManager()
            db.update_recording(
                recording_id,
                {
                    "failed": True,
                    "failed_reason": f"Task failed: {str(exc)}",
                    "failed_at_stage": "processing_task",
                },
            )

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        """Обработка повторной попытки."""
        logger.warning(f"Task {task_id} retrying: {exc}")

    def on_success(self, retval, task_id, args, kwargs):
        """Обработка успешного завершения."""
        logger.info(f"Task {task_id} completed successfully")


@celery_app.task(
    bind=True,
    base=RecordingProcessingTask,
    name="api.tasks.processing.process_single_recording",
    max_retries=2,
    default_retry_delay=300,  # 5 минут между попытками
)
def process_single_recording(
    self,
    recording_id: int,
    enable_transcription: bool = True,
    enable_topics: bool = True,
    enable_subtitles: bool = True,
    transcription_model: str | None = None,
    topic_model: str | None = None,
    topic_mode: str | None = None,
) -> dict:
    """
    Обработка одной записи (загрузка, транскрибация, темы, субтитры).

    Args:
        recording_id: ID записи
        enable_transcription: Включить транскрибацию
        enable_topics: Включить извлечение тем
        enable_subtitles: Включить генерацию субтитров
        transcription_model: Модель транскрибации
        topic_model: Модель извлечения тем
        topic_mode: Режим извлечения тем

    Returns:
        Словарь с результатом обработки
    """
    try:
        logger.info(f"[Task {self.request.id}] Processing recording {recording_id}")

        # Инициализация менеджеров
        db = DatabaseManager()
        pipeline = PipelineManager(db)

        # Получение записи
        recording = db.get_recording_by_id(recording_id)
        if not recording:
            raise ValueError(f"Recording {recording_id} not found")

        # Установка настроек обработки
        processing_preferences = {
            "enable_transcription": enable_transcription,
            "enable_topics": enable_topics,
            "enable_subtitles": enable_subtitles,
        }
        if transcription_model:
            processing_preferences["transcription_model"] = transcription_model
        if topic_model:
            processing_preferences["topic_model"] = topic_model
        if topic_mode:
            processing_preferences["topic_mode"] = topic_mode

        db.update_recording(recording_id, {"processing_preferences": processing_preferences})

        # Обработка записи
        result = pipeline._process_single_video_complete(recording)

        return {
            "recording_id": recording_id,
            "status": "completed",
            "task_id": self.request.id,
            "result": result,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"[Task {self.request.id}] Soft time limit exceeded for recording {recording_id}")
        raise self.retry(countdown=600, exc=SoftTimeLimitExceeded())  # Повтор через 10 минут

    except Exception as exc:
        logger.error(
            f"[Task {self.request.id}] Error processing recording {recording_id}: {exc}",
            exc_info=True,
        )
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    base=RecordingProcessingTask,
    name="api.tasks.processing.batch_process_recordings",
    max_retries=1,
)
def batch_process_recordings(
    self,
    recording_ids: list[int],
    enable_transcription: bool = True,
    enable_topics: bool = True,
    enable_subtitles: bool = True,
    transcription_model: str | None = None,
    topic_model: str | None = None,
    topic_mode: str | None = None,
) -> dict:
    """
    Пакетная обработка нескольких записей.

    Args:
        recording_ids: Список ID записей
        enable_transcription: Включить транскрибацию
        enable_topics: Включить извлечение тем
        enable_subtitles: Включить генерацию субтитров
        transcription_model: Модель транскрибации
        topic_model: Модель извлечения тем
        topic_mode: Режим извлечения тем

    Returns:
        Словарь с результатами обработки
    """
    try:
        logger.info(f"[Task {self.request.id}] Batch processing {len(recording_ids)} recordings")

        # Запуск задач для каждой записи
        tasks = []
        for recording_id in recording_ids:
            task = process_single_recording.apply_async(
                args=[recording_id],
                kwargs={
                    "enable_transcription": enable_transcription,
                    "enable_topics": enable_topics,
                    "enable_subtitles": enable_subtitles,
                    "transcription_model": transcription_model,
                    "topic_model": topic_model,
                    "topic_mode": topic_mode,
                },
                priority=5,  # Средний приоритет
            )
            tasks.append({"recording_id": recording_id, "task_id": task.id})

        return {
            "batch_task_id": self.request.id,
            "status": "scheduled",
            "recordings_count": len(recording_ids),
            "tasks": tasks,
        }

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error in batch processing: {exc}", exc_info=True)
        raise


@celery_app.task(
    bind=True,
    name="api.tasks.processing.generate_subtitles",
    max_retries=2,
    default_retry_delay=180,
)
def generate_subtitles(self, recording_ids: list[int]) -> dict:
    """
    Генерация субтитров для записей.

    Args:
        recording_ids: Список ID записей

    Returns:
        Словарь с результатами генерации
    """
    try:
        logger.info(f"[Task {self.request.id}] Generating subtitles for {len(recording_ids)} recordings")

        db = DatabaseManager()
        pipeline = PipelineManager(db)

        results = []
        for recording_id in recording_ids:
            recording = db.get_recording_by_id(recording_id)
            if recording:
                result = pipeline.generate_subtitles_for_recording(recording)
                results.append({"recording_id": recording_id, "success": result})
            else:
                results.append({"recording_id": recording_id, "success": False, "error": "Not found"})

        return {
            "task_id": self.request.id,
            "status": "completed",
            "results": results,
        }

    except Exception as exc:
        logger.error(f"[Task {self.request.id}] Error generating subtitles: {exc}", exc_info=True)
        raise self.retry(exc=exc)
