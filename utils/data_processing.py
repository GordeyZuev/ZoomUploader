from datetime import datetime, time
from typing import Any

from api.zoom_api import ZoomAPI
from logger import get_logger
from models.recording import MeetingRecording

from .formatting import normalize_datetime_string

logger = get_logger()


def process_meetings_data(response_data: dict[str, Any], filter_video_only: bool = True) -> list[MeetingRecording]:
    """Обработка данных встреч из API ответа. Каждая MP4-подчасть превращается в отдельную MeetingRecording."""
    meetings = response_data.get("meetings", [])
    processed_meetings = []

    mp4_priorities = {
        "shared_screen_with_speaker_view": 3,
        "shared_screen": 2,
        "active_speaker": 1,
    }

    for meeting in meetings:
        recording_files = meeting.get("recording_files", [])
        mp4_files = [f for f in recording_files if f.get("file_type") == "MP4"]

        if not mp4_files:
            if not filter_video_only:
                meeting_data = dict(meeting)
                if "source_metadata" not in meeting_data:
                    meeting_data["source_metadata"] = {}
                meeting_data["source_metadata"]["zoom_api_response"] = meeting
                processed_meetings.append(MeetingRecording(meeting_data))
            continue

        grouped: dict[str, list[dict[str, Any]]] = {}
        for f in mp4_files:
            key = f.get("recording_start") or f.get("recordingStart") or f.get("id")
            grouped.setdefault(key, []).append(f)

        parts: list[dict[str, Any]] = []
        for _, files in grouped.items():
            best = None
            best_priority = -1
            best_size = -1
            for f in files:
                p = mp4_priorities.get(f.get("recording_type"), 0)
                s = f.get("file_size", 0) or 0
                if p > best_priority or (p == best_priority and s > best_size):
                    best_priority = p
                    best_size = s
                    best = f
            if best:
                parts.append(best)

        def _sort_key(f: dict[str, Any]):
            return f.get("recording_start") or f.get("recordingStart") or ""

        parts.sort(key=_sort_key)

        for idx, part in enumerate(parts, start=1):
            part_start = part.get("recording_start") or part.get("recordingStart") or meeting.get("start_time", "")
            part_end = part.get("recording_end") or part.get("recordingEnd")

            duration_minutes = meeting.get("duration", 0)
            if part_start and part_end:
                try:
                    start_dt = datetime.fromisoformat(normalize_datetime_string(part_start))
                    end_dt = datetime.fromisoformat(normalize_datetime_string(part_end))
                    delta = end_dt - start_dt
                    duration_minutes = max(0, int(delta.total_seconds() // 60))
                except Exception as e:
                    logger.warning(f"Ignored exception: {e}")

            meeting_data = dict(meeting)
            meeting_data["recording_files"] = [part]
            meeting_data["start_time"] = part_start or meeting.get("start_time", "")
            meeting_data["duration"] = duration_minutes
            meeting_data["source_key"] = f"{meeting.get('id', '')}:{part_start}"
            meeting_data["part_index"] = idx
            meeting_data["video_file_size"] = part.get("file_size")

            # Store full Zoom API response for metadata access
            if "source_metadata" not in meeting_data:
                meeting_data["source_metadata"] = {}

            meeting_data["source_metadata"]["zoom_api_response"] = meeting

            if meeting.get("uuid"):
                meeting_data["source_metadata"]["meeting_uuid"] = meeting.get("uuid")
            if meeting.get("meeting_id"):
                meeting_data["source_metadata"]["meeting_id"] = meeting.get("meeting_id")
                logger.debug(f"Saved meeting_id from API: meeting_id={meeting.get('meeting_id')}")
            elif meeting.get("id"):
                meeting_data["source_metadata"]["meeting_id"] = meeting.get("id")
                logger.debug(f"Сохранен id как meeting_id: id={meeting.get('id')}")

            recording = MeetingRecording(meeting_data)
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
    end_date: str | None = None,
    page_size: int = 30,
    filter_video_only: bool = True,
) -> list[MeetingRecording]:
    """Получение записей по диапазону дат через API."""
    try:
        logger.info(f"Получение записей: {start_date} - {end_date or 'текущая дата'}")
        response = await api.get_recordings(page_size=page_size, from_date=start_date, to_date=end_date)

        recordings = process_meetings_data(response, filter_video_only)

        enhanced_recordings = []
        for recording in recordings:
            try:
                logger.debug(
                    f"Получение детальной информации: meeting_id={recording.meeting_id} | recording={recording.display_name}"
                )
                detailed_data = await api.get_recording_details(recording.meeting_id, include_download_token=True)

                recording.password = detailed_data.get("password")
                recording.recording_play_passcode = detailed_data.get("recording_play_passcode")
                recording.download_access_token = detailed_data.get("download_access_token")

                # Store detailed Zoom API response in source_metadata
                if not hasattr(recording, "source_metadata") or not isinstance(recording.source_metadata, dict):
                    recording.source_metadata = {}
                recording.source_metadata["zoom_api_details"] = detailed_data

                enhanced_recordings.append(recording)

            except Exception as e:
                logger.warning(f"Failed to get details for recording {recording.meeting_id}: {e}")
                enhanced_recordings.append(recording)

        logger.info(f"Processed recordings: {len(enhanced_recordings)}")

        return enhanced_recordings

    except Exception as e:
        logger.error(f"Error getting recordings: {e}")
        raise


def filter_recordings_by_duration(
    recordings: list[MeetingRecording], min_duration_minutes: int = 25
) -> list[MeetingRecording]:
    """Фильтрация записей по минимальной длительности."""
    return [recording for recording in recordings if recording.is_long_enough(min_duration_minutes)]


def filter_recordings_by_size(recordings: list[MeetingRecording], min_size_mb: int = 30) -> list[MeetingRecording]:
    """Фильтрация записей по минимальному размеру."""
    min_size_bytes = min_size_mb * 1024 * 1024
    return [recording for recording in recordings if recording.video_file_size >= min_size_bytes]


def filter_available_recordings(
    recordings: list[MeetingRecording], min_duration_minutes: int = 25, min_size_mb: int = 30
) -> list[MeetingRecording]:
    """Фильтрация записей для формирования списка доступных записей."""
    with_video = [recording for recording in recordings if recording.has_video()]
    long_enough = filter_recordings_by_duration(with_video, min_duration_minutes)
    large_enough = filter_recordings_by_size(long_enough, min_size_mb)

    counts: dict[str, int] = {}
    for r in large_enough:
        meeting_id = r.meeting_id or (r.source_metadata.get("meeting_id") if hasattr(r, "source_metadata") else None)
        key = meeting_id or r.source_key
        counts[key] = counts.get(key, 0) + 1

    for r in large_enough:
        meeting_id = r.meeting_id or (r.source_metadata.get("meeting_id") if hasattr(r, "source_metadata") else None)
        key = meeting_id or r.source_key
        try:
            total = counts.get(key, 1)
            r.total_visible_parts = total
            if hasattr(r, "source_metadata") and isinstance(r.source_metadata, dict):
                r.source_metadata["total_visible_parts"] = total
        except Exception as e:
            logger.warning(f"Ignored exception: {e}")

    return large_enough
