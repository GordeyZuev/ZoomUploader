"""Утилиты для работы с датами."""

from datetime import datetime, timedelta


def parse_date(date_str: str) -> str:
    """
    Парсит дату в различных форматах и возвращает в формате YYYY-MM-DD.

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


def parse_date_range(
    from_date: str | None = None,
    to_date: str | None = None,
    last_days: int | None = None,
) -> tuple[str, str | None]:
    """
    Парсит диапазон дат с поддержкой различных форматов и опции 'last_days'.

    Args:
        from_date: Дата начала в любом поддерживаемом формате
        to_date: Дата окончания в любом поддерживаемом формате
        last_days: Количество последних дней (0 = сегодня, 7 = последние 7 дней)

    Returns:
        Tuple (from_date, to_date) в формате YYYY-MM-DD
    """
    if last_days is not None:
        if last_days == 0:
            # Сегодня
            from_date = datetime.now().strftime("%Y-%m-%d")
            to_date = datetime.now().strftime("%Y-%m-%d")
        else:
            # Последние N дней
            to_date = datetime.now().strftime("%Y-%m-%d")
            from_date = (datetime.now() - timedelta(days=last_days)).strftime("%Y-%m-%d")
    else:
        # Если даты указаны явно, парсим их
        if from_date:
            from_date = parse_date(from_date)
        else:
            # По умолчанию: последние 14 дней
            from_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

        if to_date:
            to_date = parse_date(to_date)
        # else: to_date остаётся None (до текущего момента)

    return from_date, to_date
