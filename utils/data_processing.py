from datetime import datetime, time
from typing import Any

from api.zoom_api import ZoomAPI
from logger import get_logger
from models.recording import MeetingRecording, ProcessingStatus

from .formatting import normalize_datetime_string

logger = get_logger()


def process_meetings_data(
    response_data: dict[str, Any], filter_video_only: bool = True
) -> list[MeetingRecording]:
    """Обработка данных встреч из API ответа."""
    meetings = response_data.get('meetings', [])
    processed_meetings = []

    for meeting in meetings:
        recording = MeetingRecording(meeting)
        if not filter_video_only or recording.has_video():
            processed_meetings.append(recording)

    return processed_meetings


def filter_recordings_by_date_range(
    recordings: list[MeetingRecording], start_date: str, end_date: str | None = None
) -> list[MeetingRecording]:
    """Фильтрация записей по диапазону дат."""

    start_dt = datetime.fromisoformat(start_date)
    if end_date:
        end_dt = datetime.combine(datetime.fromisoformat(end_date).date(), time(23, 59, 59))
    else:
        end_dt = datetime.now()

    filtered_recordings = []

    for recording in recordings:
        if recording.start_time:
            try:
                normalized_time = normalize_datetime_string(recording.start_time)
                meeting_dt = datetime.fromisoformat(normalized_time)

                # Приводим все даты к одному типу (naive)
                if meeting_dt.tzinfo is not None:
                    meeting_dt = meeting_dt.replace(tzinfo=None)

                if start_dt <= meeting_dt <= end_dt:
                    filtered_recordings.append(recording)
            except ValueError:
                continue

    return filtered_recordings


async def get_recordings_by_date_range(
    api: ZoomAPI,
    start_date: str,
    end_date: str = None,
    page_size: int = 30,
    filter_video_only: bool = True,
) -> list[MeetingRecording]:
    """Получение записей по диапазону дат через API."""
    try:
        logger.info(f"Получение записей: {start_date} - {end_date or 'текущая дата'}")
        response = await api.get_recordings(
            page_size=page_size, from_date=start_date, to_date=end_date
        )

        recordings = process_meetings_data(response, filter_video_only)

        # Получаем детальную информацию с download_access_token для каждой записи
        enhanced_recordings = []
        for recording in recordings:
            try:
                logger.debug(f"Получение детальной информации для записи {recording.meeting_id}")
                detailed_data = await api.get_recording_details(
                    recording.meeting_id, include_download_token=True
                )

                # Обновляем запись с детальной информацией
                recording.password = detailed_data.get('password')
                recording.recording_play_passcode = detailed_data.get('recording_play_passcode')
                recording.download_access_token = detailed_data.get('download_access_token')

                enhanced_recordings.append(recording)

            except Exception as e:
                logger.warning(
                    f"Не удалось получить детальную информацию для записи {recording.meeting_id}: {e}"
                )
                # Добавляем запись без детальной информации
                enhanced_recordings.append(recording)

        logger.info(f"Обработано записей: {len(enhanced_recordings)}")

        return enhanced_recordings

    except Exception as e:
        logger.error(f"Ошибка получения записей: {e}")
        raise


def filter_recordings_by_status(
    recordings: list[MeetingRecording], status: ProcessingStatus
) -> list[MeetingRecording]:
    """Фильтрация записей по статусу."""
    return [recording for recording in recordings if recording.status == status]


def group_recordings_by_topic(
    recordings: list[MeetingRecording],
) -> dict[str, list[MeetingRecording]]:
    """Группировка записей по теме."""
    grouped = {}

    for recording in recordings:
        topic = recording.topic or "Без названия"
        if topic not in grouped:
            grouped[topic] = []
        grouped[topic].append(recording)

    return grouped


def group_recordings_by_date(
    recordings: list[MeetingRecording],
) -> dict[str, list[MeetingRecording]]:
    """Группировка записей по дате."""
    from datetime import datetime

    grouped = {}

    for recording in recordings:
        try:
            normalized_time = normalize_datetime_string(recording.start_time)
            meeting_dt = datetime.fromisoformat(normalized_time)
            date_key = meeting_dt.strftime("%d.%m.%Y")
        except Exception:
            date_key = "Неизвестная дата"

        if date_key not in grouped:
            grouped[date_key] = []
        grouped[date_key].append(recording)

    return grouped


def filter_recordings_by_duration(
    recordings: list[MeetingRecording], min_duration_minutes: int = 30
) -> list[MeetingRecording]:
    """Фильтрация записей по минимальной длительности."""
    return [recording for recording in recordings if recording.is_long_enough(min_duration_minutes)]


def filter_recordings_by_size(
    recordings: list[MeetingRecording], min_size_mb: int = 30
) -> list[MeetingRecording]:
    """Фильтрация записей по минимальному размеру."""
    min_size_bytes = min_size_mb * 1024 * 1024
    return [recording for recording in recordings if recording.video_file_size >= min_size_bytes]


def filter_available_recordings(
    recordings: list[MeetingRecording], min_duration_minutes: int = 30, min_size_mb: int = 30
) -> list[MeetingRecording]:
    """Фильтрация записей для формирования списка доступных записей."""
    with_video = [recording for recording in recordings if recording.has_video()]
    long_enough = filter_recordings_by_duration(with_video, min_duration_minutes)
    large_enough = filter_recordings_by_size(long_enough, min_size_mb)

    return large_enough


def filter_ready_for_processing(recordings: list[MeetingRecording]) -> list[MeetingRecording]:
    """Фильтрация записей, готовых для пост-обработки."""
    return [recording for recording in recordings if recording.is_ready_for_processing()]


def filter_ready_for_upload(recordings: list[MeetingRecording]) -> list[MeetingRecording]:
    """Фильтрация записей, готовых для загрузки на платформы."""
    return [recording for recording in recordings if recording.is_ready_for_upload()]


def get_pipeline_statistics(recordings: list[MeetingRecording]) -> dict[str, Any]:
    """Получение статистики пайплайна обработки."""
    total = len(recordings)

    stats = {
        'total_recordings': total,
        'long_enough': len(filter_recordings_by_duration(recordings)),
        'ready_for_processing': len(filter_ready_for_processing(recordings)),
        'ready_for_upload': len(filter_ready_for_upload(recordings)),
        'downloaded': len([r for r in recordings if r.is_downloaded()]),
        'processed': len([r for r in recordings if r.status.value == 'processed']),
        'youtube_uploaded': len(
            [r for r in recordings if r.youtube_status.value == 'uploaded_youtube']
        ),
        'vk_uploaded': len([r for r in recordings if r.vk_status.value == 'uploaded_vk']),
        'failed': len([r for r in recordings if r.is_failed()]),
    }

    if total > 0:
        stats['pipeline_progress'] = {
            'downloaded_pct': round((stats['downloaded'] / total) * 100, 1),
            'processed_pct': round((stats['processed'] / total) * 100, 1),
            'youtube_uploaded_pct': round((stats['youtube_uploaded'] / total) * 100, 1),
            'vk_uploaded_pct': round((stats['vk_uploaded'] / total) * 100, 1),
        }

    return stats


def get_recordings_statistics(recordings: list[MeetingRecording]) -> dict[str, Any]:
    """Получение статистики по записям."""
    from .formatting import format_duration, format_file_size

    if not recordings:
        return {
            'total_recordings': 0,
            'total_duration_minutes': 0,
            'total_video_size_bytes': 0,
            'total_chat_size_bytes': 0,
            'status_counts': {},
            'topics_count': 0,
        }

    total_duration = sum(rec.duration for rec in recordings)
    total_video_size = sum(rec.video_file_size for rec in recordings)
    total_chat_size = sum(rec.chat_file_size for rec in recordings)

    status_counts = {}
    for recording in recordings:
        status = recording.status.value
        status_counts[status] = status_counts.get(status, 0) + 1

    topics = set(rec.topic for rec in recordings if rec.topic)

    return {
        'total_recordings': len(recordings),
        'total_duration_minutes': total_duration,
        'total_duration_formatted': format_duration(total_duration),
        'total_video_size_bytes': total_video_size,
        'total_video_size_formatted': format_file_size(total_video_size),
        'total_chat_size_bytes': total_chat_size,
        'total_chat_size_formatted': format_file_size(total_chat_size),
        'status_counts': status_counts,
        'topics_count': len(topics),
        'topics': list(topics),
    }
