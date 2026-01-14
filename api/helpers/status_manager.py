"""Helper для автоматического обновления агрегированного статуса recording.

Главный статус (ProcessingStatus) вычисляется на основе:
- processing_stages (детальные этапы)
- outputs (targets для загрузки)
"""

from database.models import RecordingModel
from models.recording import (
    ProcessingStageStatus,
    ProcessingStatus,
    TargetStatus,
)


def compute_aggregate_status(recording: RecordingModel) -> ProcessingStatus:
    """
    Вычислить агрегированный статус recording из processing_stages и outputs.

    Логика:
    1. Если нет stages → статус из текущего workflow (INITIALIZED, DOWNLOADED, PROCESSED)
    2. Если есть stages:
       - Все PENDING → PROCESSED (ожидают запуска)
       - Хотя бы один IN_PROGRESS → PREPARING (или TRANSCRIBING для legacy)
       - Все COMPLETED → TRANSCRIBED
    3. Если есть outputs и все stages COMPLETED:
       - Хотя бы один UPLOADING → UPLOADING
       - Все UPLOADED → READY
       - Иначе → TRANSCRIBED (ожидают загрузки)

    Args:
        recording: RecordingModel

    Returns:
        ProcessingStatus
    """
    current_status = recording.status

    # Если нет processing_stages, возвращаем текущий статус или базовый workflow
    if not recording.processing_stages:
        # Базовый workflow без детальных этапов
        if current_status in [
            ProcessingStatus.INITIALIZED,
            ProcessingStatus.DOWNLOADING,
            ProcessingStatus.DOWNLOADED,
            ProcessingStatus.PROCESSING,
            ProcessingStatus.PROCESSED,
        ]:
            return current_status
        return ProcessingStatus.PROCESSED

    # Анализируем processing_stages
    stages = recording.processing_stages
    stage_statuses = [stage.status for stage in stages]

    # Все этапы в ожидании
    if all(status == ProcessingStageStatus.PENDING for status in stage_statuses):
        return ProcessingStatus.PROCESSED  # Готово к запуску обработки

    # Хотя бы один этап в процессе
    if any(status == ProcessingStageStatus.IN_PROGRESS for status in stage_statuses):
        return ProcessingStatus.PREPARING

    # Все этапы завершены
    if all(status == ProcessingStageStatus.COMPLETED for status in stage_statuses):
        # Проверяем outputs
        if recording.outputs:
            output_statuses = [output.status for output in recording.outputs]

            # Хотя бы один в процессе загрузки
            if any(status == TargetStatus.UPLOADING for status in output_statuses):
                return ProcessingStatus.UPLOADING

            # Все загружены
            if all(status == TargetStatus.UPLOADED for status in output_statuses):
                return ProcessingStatus.READY

            # Есть незагруженные
            return ProcessingStatus.TRANSCRIBED  # Готово к загрузке

        # Нет outputs → просто транскрибировано
        return ProcessingStatus.TRANSCRIBED

    # Смешанные статусы (частично завершено)
    return ProcessingStatus.PREPARING


def update_aggregate_status(recording: RecordingModel) -> ProcessingStatus:
    """
    Обновить агрегированный статус recording.

    Args:
        recording: RecordingModel

    Returns:
        Новый ProcessingStatus
    """
    new_status = compute_aggregate_status(recording)
    recording.status = new_status
    return new_status


def should_allow_download(recording: RecordingModel, allow_skipped: bool = False) -> bool:
    """
    Проверить, можно ли запустить загрузку recording из источника.

    Загрузка разрешена, если:
    1. Recording в статусе INITIALIZED (не SKIPPED, если не разрешено явно)
    2. Не в процессе загрузки (DOWNLOADING)

    Args:
        recording: RecordingModel
        allow_skipped: Разрешить загрузку SKIPPED записей (из конфига/query param)

    Returns:
        True если загрузка разрешена
    """
    # Проверяем статус SKIPPED
    if recording.status == ProcessingStatus.SKIPPED and not allow_skipped:
        return False

    # Разрешаем загрузку только из INITIALIZED или SKIPPED (если allow_skipped=True)
    if recording.status == ProcessingStatus.INITIALIZED:
        return True

    if recording.status == ProcessingStatus.SKIPPED and allow_skipped:
        return True

    # Из других статусов загрузка не имеет смысла
    return False


def should_allow_processing(recording: RecordingModel, allow_skipped: bool = False) -> bool:
    """
    Проверить, можно ли запустить обработку (process) recording.

    Обработка разрешена, если:
    1. Recording в статусе DOWNLOADED (уже загружено)
    2. Не SKIPPED (если не разрешено явно)

    Args:
        recording: RecordingModel
        allow_skipped: Разрешить обработку SKIPPED записей (из конфига/query param)

    Returns:
        True если обработка разрешена
    """
    # Проверяем статус SKIPPED
    if recording.status == ProcessingStatus.SKIPPED and not allow_skipped:
        return False

    # Разрешаем обработку из DOWNLOADED или PROCESSED (повторная обработка)
    if recording.status in [ProcessingStatus.DOWNLOADED, ProcessingStatus.PROCESSED]:
        return True

    # Если SKIPPED и allow_skipped=True, разрешаем
    if recording.status == ProcessingStatus.SKIPPED and allow_skipped:
        return True

    return False


def should_allow_transcription(recording: RecordingModel, allow_skipped: bool = False) -> bool:
    """
    Проверить, можно ли запустить транскрипцию для recording.

    Транскрипция разрешена, если:
    1. Recording в статусе PROCESSED (базовая обработка завершена)
    2. Не SKIPPED (если не разрешено явно)
    3. Нет активных processing_stages (IN_PROGRESS)
    4. TRANSCRIBE stage либо отсутствует, либо в статусе PENDING или FAILED

    Args:
        recording: RecordingModel
        allow_skipped: Разрешить транскрипцию SKIPPED записей (из конфига/query param)

    Returns:
        True если транскрипция разрешена
    """
    # Проверяем статус SKIPPED
    if recording.status == ProcessingStatus.SKIPPED and not allow_skipped:
        return False

    # Проверка базового статуса
    if recording.status not in [
        ProcessingStatus.PROCESSED,
        ProcessingStatus.TRANSCRIBED,
        ProcessingStatus.PREPARING,
        ProcessingStatus.SKIPPED,  # Разрешаем если allow_skipped=True
    ]:
        return False

    # Проверяем processing_stages
    if not recording.processing_stages:
        # Нет stages - можно создать
        return True

    # Ищем TRANSCRIBE stage
    from models.recording import ProcessingStageType

    transcribe_stage = None
    for stage in recording.processing_stages:
        if stage.stage_type == ProcessingStageType.TRANSCRIBE:
            transcribe_stage = stage
            break

        # Запрещаем если какой-то этап в процессе
        if stage.status == ProcessingStageStatus.IN_PROGRESS:
            return False

    # Если нет TRANSCRIBE stage - можно создать
    if transcribe_stage is None:
        return True

    # Если TRANSCRIBE stage существует - проверяем его статус
    # Можно перезапустить только если PENDING или FAILED
    if transcribe_stage.status in [
        ProcessingStageStatus.PENDING,
        ProcessingStageStatus.FAILED,
    ]:
        return True

    # Если уже COMPLETED или IN_PROGRESS - нельзя
    return False


def should_allow_upload(
    recording: RecordingModel, target_type: str, allow_skipped: bool = False
) -> bool:
    """
    Проверить, можно ли запустить загрузку на платформу.

    Загрузка разрешена, если:
    1. Recording не в статусе SKIPPED (если не разрешено явно)
    2. Все processing_stages завершены (COMPLETED) или нет stages
    3. Target для этой платформы либо отсутствует, либо NOT_UPLOADED или FAILED

    Args:
        recording: RecordingModel
        target_type: Тип платформы (TargetType value)
        allow_skipped: Разрешить загрузку SKIPPED записей (из конфига/query param)

    Returns:
        True если загрузка разрешена
    """
    # Проверяем статус SKIPPED
    if recording.status == ProcessingStatus.SKIPPED and not allow_skipped:
        return False

    # Проверяем, что все stages завершены (если есть)
    if recording.processing_stages:
        all_completed = all(
            stage.status == ProcessingStageStatus.COMPLETED for stage in recording.processing_stages
        )
        if not all_completed:
            return False

    # Ищем target для этой платформы
    target = None
    for output in recording.outputs:
        if output.target_type == target_type:
            target = output
            break

    # Если нет target - можно создать
    if target is None:
        return True

    # Если target существует - проверяем его статус
    if target.status in [TargetStatus.NOT_UPLOADED, TargetStatus.FAILED]:
        return True

    # Если уже UPLOADED или UPLOADING - нельзя
    return False

