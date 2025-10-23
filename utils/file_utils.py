"""
Утилиты для работы с файлами
"""

import csv
import json

from models.recording import MeetingRecording


def save_recordings_to_json(
    recordings: list[MeetingRecording], filename: str = 'meetings.json'
) -> None:
    """Сохранение записей в JSON файл."""
    data = [recording.to_dict() for recording in recordings]
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_recordings_to_csv(
    recordings: list[MeetingRecording], filename: str = 'meetings.csv'
) -> None:
    """Сохранение записей в CSV файл."""
    if not recordings:
        return

    fieldnames = [
        'topic',
        'start_time',
        'duration',
        'duration_formatted',
        'video_file_size',
        'video_file_size_formatted',
        'chat_file_size',
        'chat_file_size_formatted',
        'status',
        'auto_delete_date',
        'meeting_id',
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for recording in recordings:
            data = recording.to_dict()
            csv_row = {field: data.get(field, '') for field in fieldnames}
            writer.writerow(csv_row)


def load_recordings_from_json(filename: str) -> list[dict]:
    """Загрузка записей из JSON файла."""
    with open(filename, encoding='utf-8') as f:
        return json.load(f)


def export_recordings_summary(
    recordings: list[MeetingRecording], filename: str = 'summary.txt'
) -> None:
    """Экспорт краткого отчета о записях."""
    from .data_processing import get_recordings_statistics

    stats = get_recordings_statistics(recordings)

    with open(filename, 'w', encoding='utf-8') as f:
        f.write("=== ОТЧЕТ ПО ЗАПИСЯМ ZOOM ===\n\n")
        f.write(f"Всего записей: {stats['total_recordings']}\n")
        f.write(f"Общая длительность: {stats['total_duration_formatted']}\n")
        f.write(f"Общий размер видео: {stats['total_video_size_formatted']}\n")
        f.write(f"Общий размер чатов: {stats['total_chat_size_formatted']}\n")
        f.write(f"Количество тем: {stats['topics_count']}\n\n")

        f.write("Статистика по статусам:\n")
        for status, count in stats['status_counts'].items():
            f.write(f"  {status}: {count}\n")

        f.write("\nТемы:\n")
        for topic in stats['topics']:
            f.write(f"  - {topic}\n")

        f.write("\nДетальная информация:\n")
        f.write("-" * 80 + "\n")

        for i, recording in enumerate(recordings, 1):
            f.write(f"{i}. {recording.topic}\n")
            f.write(f"   Дата: {recording.start_time}\n")
            f.write(f"   Длительность: {recording.format_duration(recording.duration)}\n")
            f.write(f"   Статус: {recording.status.value}\n")
            f.write(f"   Размер видео: {recording.format_file_size(recording.video_file_size)}\n")
            if recording.error_message:
                f.write(f"   Ошибка: {recording.error_message}\n")
            f.write("\n")
