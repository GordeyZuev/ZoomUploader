"""API validators and parsers"""

from datetime import date, datetime, timedelta
from typing import Any

from pydantic import field_validator


class DateRangeMixin:
    """Миксин для работы с диапазонами дат."""

    @field_validator("from_date", "to_date", mode="before")
    @classmethod
    def parse_date_field(cls, v: Any) -> date | None:
        """
        Парсит дату из различных форматов.

        Поддерживаемые форматы:
        - ISO: 2024-12-01, 2024-12-01T10:00:00
        - Европейский: 01/12/2024, 01-12-2024
        - Короткий год: 01/12/24, 01-12-24
        """
        if v is None or v == "":
            return None

        if isinstance(v, date):
            return v

        if isinstance(v, datetime):
            return v.date()

        if isinstance(v, str):
            v = v.strip()

            # Пробуем стандартные форматы
            formats = [
                "%Y-%m-%d",  # 2024-12-01
                "%d/%m/%Y",  # 01/12/2024
                "%d-%m-%Y",  # 01-12-2024
                "%d.%m.%Y",  # 01.12.2024
                "%d/%m/%y",  # 01/12/24
                "%d-%m-%y",  # 01-12-24
                "%d.%m.%y",  # 01.12.24
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue

        raise ValueError(f"Неверный формат даты: {v}. Используйте: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY или DD.MM.YYYY")

    @staticmethod
    def resolve_date_range(
        from_date: date | None,
        to_date: date | None,
        last_days: int | None,
    ) -> tuple[date, date | None]:
        """
        Вычисляет итоговый диапазон дат с учётом приоритетов.

        Логика:
        1. Если указан last_days — используется он (приоритет)
        2. Иначе используются from_date/to_date
        3. По умолчанию: последние 14 дней
        """
        if last_days is not None:
            if last_days == 0:
                # Только сегодня
                today = date.today()
                return today, today
            else:
                # Последние N дней
                to_date = date.today()
                from_date = to_date - timedelta(days=last_days)
                return from_date, to_date

        # Используем явно указанные даты
        if from_date is None:
            # По умолчанию: последние 14 дней
            from_date = date.today() - timedelta(days=14)

        return from_date, to_date
