"""Base Pydantic model configurations"""

from pydantic import ConfigDict

# Базовая конфигурация для всех схем
# Сохраняет порядок полей как в определении класса (не сортирует по алфавиту)
BASE_MODEL_CONFIG = ConfigDict(
    # Сохранить порядок полей в JSON Schema
    json_schema_serialization_defaults_required=True,
    # Разрешить populate_by_name для ORM совместимости
    populate_by_name=True,
    # Строгая валидация типов
    strict=False,
    # Использовать enum значения вместо имен
    use_enum_values=False,
)

# Конфигурация для ORM моделей (response schemas)
ORM_MODEL_CONFIG = ConfigDict(
    from_attributes=True,
    json_schema_serialization_defaults_required=True,
    populate_by_name=True,
)
