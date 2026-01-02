from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import settings


def normalize_datetime_string(date_string: str) -> str:
    """Нормализация строки даты для корректного парсинга."""
    if not date_string:
        return date_string

    time_str = date_string
    if time_str.endswith("Z"):
        time_str = time_str[:-1]
    if time_str.endswith("+00:00"):
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


def format_date(date_input: str | datetime) -> str:
    """Форматирование даты в удобочитаемый вид с конвертацией в локальный часовой пояс.

    Ожидает формат Zoom API: "2021-03-18T05:41:36Z" (UTC с 'Z' в конце).
    """
    try:
        # Если передан datetime объект
        if isinstance(date_input, datetime):
            dt = date_input
        else:
            # Если передана строка, ожидаем формат Zoom API (с 'Z' в конце)
            date_str = str(date_input).strip()

            # Заменяем 'Z' на '+00:00' для правильного парсинга UTC
            if date_str.endswith("Z"):
                date_str = date_str[:-1] + "+00:00"
            else:
                # Если нет 'Z', добавляем UTC (для обратной совместимости)
                if "T" in date_str and "+" not in date_str and "-" not in date_str[-6:]:
                    date_str = date_str + "+00:00"

            dt = datetime.fromisoformat(date_str)

        # Если datetime не имеет timezone, считаем что это UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))

        # Конвертируем в локальный часовой пояс из настроек
        try:
            local_tz = ZoneInfo(settings.timezone)
            dt_local = dt.astimezone(local_tz)
        except Exception:
            # Если не удалось получить часовой пояс из настроек, используем UTC
            dt_local = dt.astimezone(ZoneInfo("UTC"))

        return dt_local.strftime("%d.%m.%Y %H:%M:%S")
    except (ValueError, TypeError):
        return str(date_input) if date_input else ""
