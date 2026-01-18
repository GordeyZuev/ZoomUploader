"""Date utilities"""

from datetime import UTC, datetime


def parse_date(date_str: str) -> str:
    """
    Parse date in different formats and return in format YYYY-MM-DD.

    Поддерживаемые форматы:
    - YYYY-MM-DD (стандартный)
    - DD-MM-YYYY (европейский)
    - DD/MM/YYYY (с слэшами)
    - DD-MM-YY (короткий год)
    - DD/MM/YY (короткий год)
    """
    if not date_str:
        return date_str

    date_str = date_str.strip()

    formats = [
        "%Y-%m-%d",  # YYYY-MM-DD
        "%d-%m-%Y",  # DD-MM-YYYY
        "%d/%m/%Y",  # DD/MM/YYYY
        "%d-%m-%y",  # DD-MM-YY
        "%d/%m/%y",  # DD/MM/YY
    ]

    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return date_str


def parse_from_date_to_datetime(date_str: str) -> datetime:
    """
    Parse date string to datetime at start of day (00:00:00) with UTC timezone.

    Used for 'from_date' filters (>=).

    Args:
        date_str: Date string in any supported format (YYYY-MM-DD, DD-MM-YYYY, etc.)

    Returns:
        datetime object at 00:00:00 UTC

    Example:
        >>> parse_from_date_to_datetime("2024-12-01")
        datetime(2024, 12, 1, 0, 0, 0, tzinfo=UTC)
    """
    parsed = parse_date(date_str)
    return datetime.strptime(parsed, "%Y-%m-%d").replace(tzinfo=UTC)


def parse_to_date_to_datetime(date_str: str) -> datetime:
    """
    Parse date string to datetime at end of day (23:59:59) with UTC timezone.

    Used for 'to_date' filters (<=).

    Args:
        date_str: Date string in any supported format (YYYY-MM-DD, DD-MM-YYYY, etc.)

    Returns:
        datetime object at 23:59:59 UTC

    Example:
        >>> parse_to_date_to_datetime("2024-12-31")
        datetime(2024, 12, 31, 23, 59, 59, tzinfo=UTC)
    """
    parsed = parse_date(date_str)
    dt = datetime.strptime(parsed, "%Y-%m-%d").replace(tzinfo=UTC)
    # End of day
    return dt.replace(hour=23, minute=59, second=59)
