from datetime import datetime


def normalize_datetime_string(date_string: str) -> str:
    """Нормализация строки даты для корректного парсинга."""
    if not date_string:
        return date_string

    time_str = date_string
    if time_str.endswith('Z'):
        time_str = time_str[:-1]
    if time_str.endswith('+00:00'):
        time_str = time_str[:-6]

    return time_str


def format_duration(minutes: int) -> str:
    """Форматирование длительности в удобочитаемый вид."""
    if minutes == 0:
        return "0м"

    hours = minutes // 60
    mins = minutes % 60

    if hours > 0:
        if mins > 0:
            return f"{hours}ч {mins}м"
        else:
            return f"{hours}ч"
    else:
        return f"{mins}м"


def format_file_size(size_bytes: int) -> str:
    """Форматирование размера файла в удобочитаемый вид."""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0

    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1

    if i == 0:
        return f"{size_bytes:.0f} {size_names[i]}"
    else:
        return f"{size_bytes:.1f} {size_names[i]}"


def format_date(date_string: str, input_format: str = "%Y-%m-%dT%H:%M:%SZ") -> str:
    """Форматирование даты в удобочитаемый вид."""
    try:
        normalized_time = normalize_datetime_string(date_string)
        dt = datetime.fromisoformat(normalized_time)
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except (ValueError, TypeError):
        return date_string


def format_status(status: str) -> str:
    """Форматирование статуса на русском языке."""
    status_translations = {
        'pending': 'Ожидает',
        'downloading': 'Загружается',
        'downloaded': 'Загружено',
        'processing': 'Обрабатывается',
        'processed': 'Обработано',
        'uploading': 'Выгружается',
        'uploaded': 'Выгружено',
        'failed': 'Ошибка',
        'skipped': 'Пропущено',
    }

    return status_translations.get(status, status)


def format_meeting_info(recording) -> str:
    """Форматирование информации о встрече для вывода."""
    topic = recording.topic or "Без названия"
    date = format_date(recording.start_time)
    duration = format_duration(recording.duration)
    status = format_status(recording.status.value)

    info = f"📅 {topic}\n"
    info += f"   ⏰ Дата: {date}\n"
    info += f"   ⏱️  Длительность: {duration}\n"
    info += f"   📊 {status}\n"

    if recording.video_file_size > 0:
        video_size = format_file_size(recording.video_file_size)
        info += f"   🎬 Видео: {video_size}\n"

    if recording.chat_file_size > 0:
        chat_size = format_file_size(recording.chat_file_size)
        info += f"   💬 Чат: {chat_size}\n"

    if recording.error_message:
        info += f"   ❌ Ошибка: {recording.error_message}\n"

    return info
