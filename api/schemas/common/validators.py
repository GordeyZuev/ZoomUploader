"""Common Pydantic schema validators

Содержит только специфичные валидаторы, которые невозможно реализовать через Field constraints.
Для базовых проверок используйте встроенные возможности Pydantic:
- Field(min_length=X, max_length=Y) для длины строк
- Field(gt=0, le=100) для диапазонов чисел
- Field(pattern=r"regex") для regex валидации формата строки
- @field_validator с mode="before" для преобразований (strip, lower, etc)
"""

import re


def validate_regex_pattern(v: str | None, field_name: str = "pattern") -> str | None:
    """
    Валидация regex паттерна.

    Args:
        v: Regex паттерн для валидации
        field_name: Название поля (для сообщения об ошибке)

    Returns:
        Валидированный паттерн или None

    Raises:
        ValueError: Если regex паттерн неверный
    """
    if v is not None:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"Неверный regex паттерн '{field_name}': {e}")
    return v


def validate_regex_patterns(v: list[str] | None, field_name: str = "patterns") -> list[str] | None:
    """
    Валидация списка regex паттернов.

    Args:
        v: Список regex паттернов
        field_name: Название поля (для сообщения об ошибке)

    Returns:
        Валидированный список или None

    Raises:
        ValueError: Если хоть один regex паттерн неверный
    """
    if v is not None:
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as e:
                raise ValueError(f"Неверный regex паттерн в '{field_name}': {e}")
    return v


def clean_and_deduplicate_strings(v: list[str] | None) -> list[str] | None:
    """
    Очистка и дедупликация списка строк.

    - Убирает пробелы в начале/конце (strip)
    - Удаляет пустые строки
    - Удаляет дубликаты (сохраняя порядок)
    - Возвращает None если список пуст после очистки

    Пример использования:
    ```python
    keywords: list[str] | None = Field(None)

    @field_validator("keywords", mode="before")
    @classmethod
    def clean_keywords(cls, v: list[str] | None) -> list[str] | None:
        return clean_and_deduplicate_strings(v)
    ```

    Args:
        v: Список строк

    Returns:
        Очищенный список без дубликатов или None
    """
    if v is None:
        return None

    # Очистка и фильтрация
    cleaned = [s.strip() for s in v if isinstance(s, str) and s.strip()]

    if not cleaned:
        return None

    # Дедупликация с сохранением порядка
    seen = set()
    deduplicated = []
    for item in cleaned:
        if item not in seen:
            seen.add(item)
            deduplicated.append(item)

    return deduplicated
