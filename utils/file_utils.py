import csv
import json

from models.recording import MeetingRecording

from .data_processing import get_recordings_statistics
from .formatting import format_duration, format_file_size


def save_recordings_to_json(recordings: list[MeetingRecording], filename: str = "meetings.json") -> None:
    """Сохранение записей в JSON файл."""
    data = []
    for recording in recordings:
        record_data = {
            "display_name": recording.display_name,
            "start_time": recording.start_time,
            "duration": recording.duration,
            "status": recording.status.value if hasattr(recording.status, "value") else str(recording.status),
            "video_file_size": recording.video_file_size,
            "local_video_path": recording.local_video_path,
            "processed_video_path": recording.processed_video_path,
            "db_id": recording.db_id,
        }
        data.append(record_data)
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_recordings_to_csv(recordings: list[MeetingRecording], filename: str = "meetings.csv") -> None:
    """Сохранение записей в CSV файл."""
    if not recordings:
        return

    fieldnames = [
        "display_name",
        "start_time",
        "duration",
        "duration_formatted",
        "video_file_size",
        "video_file_size_formatted",
        "status",
        "db_id",
    ]

    with open(filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for recording in recordings:
            csv_row = {
                "display_name": recording.display_name or "",
                "start_time": recording.start_time or "",
                "duration": recording.duration or 0,
                "duration_formatted": format_duration(recording.duration) if recording.duration else "",
                "video_file_size": recording.video_file_size or 0,
                "video_file_size_formatted": format_file_size(recording.video_file_size)
                if recording.video_file_size
                else "",
                "status": recording.status.value if hasattr(recording.status, "value") else str(recording.status),
                "db_id": recording.db_id or "",
            }
            writer.writerow(csv_row)


def load_recordings_from_json(filename: str) -> list[dict]:
    """Загрузка записей из JSON файла."""
    with open(filename, encoding="utf-8") as f:
        return json.load(f)


def export_recordings_summary(recordings: list[MeetingRecording], filename: str = "summary.txt") -> None:
    """Экспорт краткого отчета о записях."""
    stats = get_recordings_statistics(recordings)

    with open(filename, "w", encoding="utf-8") as f:
        f.write("=== ОТЧЕТ ПО ЗАПИСЯМ ZOOM ===\n\n")
        f.write(f"Всего записей: {stats['total_recordings']}\n")
        f.write(f"Общая длительность: {stats['total_duration_formatted']}\n")
        f.write(f"Общий размер видео: {stats['total_video_size_formatted']}\n")
        f.write(f"Общий размер чатов: {stats['total_chat_size_formatted']}\n")
        f.write(f"Количество тем: {stats['topics_count']}\n\n")

        f.write("Статистика по статусам:\n")
        for status, count in stats["status_counts"].items():
            f.write(f"  {status}: {count}\n")

        f.write("\nТемы:\n")
        for topic in stats["topics"]:
            f.write(f"  - {topic}\n")

        f.write("\nДетальная информация:\n")
        f.write("-" * 80 + "\n")

        for i, recording in enumerate(recordings, 1):
            f.write(f"{i}. {recording.display_name or 'Без названия'}\n")
            f.write(f"   Дата: {recording.start_time or 'Неизвестно'}\n")
            f.write(f"   Длительность: {format_duration(recording.duration) if recording.duration else '0 мин'}\n")
            f.write(
                f"   Статус: {recording.status.value if hasattr(recording.status, 'value') else str(recording.status)}\n"
            )
            if recording.video_file_size:
                f.write(f"   Размер видео: {format_file_size(recording.video_file_size)}\n")
            f.write("\n")
