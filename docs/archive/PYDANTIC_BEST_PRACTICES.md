# Pydantic Best Practices - Лучшие практики работы с Pydantic схемами

## 🎯 Основные принципы

### 1. Используйте встроенные возможности Pydantic

**❌ Плохо:**
```python
@field_validator("age")
@classmethod
def validate_age(cls, v: int) -> int:
    if v <= 0:
        raise ValueError("Возраст должен быть положительным")
    return v
```

**✅ Хорошо:**
```python
age: int = Field(..., gt=0, description="Возраст")
```

### 2. Используйте Field constraints

Встроенные constraints Pydantic:
- `min_length`, `max_length` - для строк
- `gt`, `ge`, `lt`, `le` - для чисел
- `pattern` - для regex валидации строки
- `min_items`, `max_items` - для списков

**Пример:**
```python
from pydantic import BaseModel, Field

class User(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    age: int = Field(..., gt=0, le=150)
    email: str = Field(..., pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
```

### 3. Сохраняйте порядок полей в Swagger

**Используйте BASE_MODEL_CONFIG:**

```python
from pydantic import BaseModel
from api.schemas.common import BASE_MODEL_CONFIG

class MyModel(BaseModel):
    model_config = BASE_MODEL_CONFIG  # Сохранит порядок полей
    
    # Поля будут в таком порядке в Swagger UI
    id: int
    name: str
    created_at: datetime
```

**Для ORM моделей:**

```python
from api.schemas.common import ORM_MODEL_CONFIG

class MyResponse(BaseModel):
    model_config = ORM_MODEL_CONFIG  # from_attributes + порядок полей
    
    id: int
    name: str
```

## 🛠️ Кастомные валидаторы

### Когда использовать кастомные валидаторы?

**✅ Используйте для:**
- Проверки валидности самих regex паттернов
- Сложной кросс-полевой валидации
- Специфичной бизнес-логики
- Очистки данных (mode="before")

**❌ НЕ используйте для:**
- Простых проверок длины, диапазона (используйте Field)
- Проверки положительных чисел (используйте `gt=0`)
- Проверки email, URL (используйте `EmailStr`, `HttpUrl`)

### Примеры кастомных валидаторов

**Очистка данных (mode="before"):**
```python
from pydantic import BaseModel, Field, field_validator
from api.schemas.common.validators import strip_and_validate_name

class Template(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    
    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return strip_and_validate_name(v)  # Очистит от пробелов
```

**Валидация regex паттерна:**
```python
from api.schemas.common.validators import validate_regex_pattern

class Rule(BaseModel):
    pattern: str = Field(..., description="Regex паттерн")
    
    @field_validator("pattern")
    @classmethod
    def check_pattern(cls, v: str) -> str:
        return validate_regex_pattern(v, field_name="pattern")
```

**Кросс-полевая валидация:**
```python
from pydantic import model_validator

class DateRange(BaseModel):
    start_date: datetime
    end_date: datetime
    
    @model_validator(mode="after")
    def check_dates(self) -> "DateRange":
        if self.end_date < self.start_date:
            raise ValueError("end_date должна быть позже start_date")
        return self
```

## 📦 Общие валидаторы

В `api.schemas.common.validators` доступны:

### ✅ Рекомендуется использовать:

```python
from api.schemas.common.validators import (
    strip_and_validate_name,     # Очистка названий
    validate_regex_pattern,       # Валидация regex паттерна
    validate_regex_patterns,      # Валидация списка паттернов
    clean_string_list,            # Очистка списка строк
)
```

### ⚠️ Deprecated (используйте Field вместо):

```python
validate_name()           # → Field(min_length=X, max_length=Y)
validate_positive_int()   # → Field(gt=0)
```

## 🎨 Структура схем

### Порядок определения в классе:

1. **model_config** - всегда первым
2. **Обязательные поля**
3. **Опциональные поля**
4. **Валидаторы** - в конце

**Пример:**
```python
from pydantic import BaseModel, Field, field_validator
from api.schemas.common import BASE_MODEL_CONFIG

class Template(BaseModel):
    # 1. Config
    model_config = BASE_MODEL_CONFIG
    
    # 2. Обязательные поля
    name: str = Field(..., min_length=3, max_length=255)
    platform: str
    
    # 3. Опциональные поля
    description: str | None = None
    is_active: bool = True
    
    # 4. Валидаторы
    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return strip_and_validate_name(v)
```

## 📝 Документация полей

Всегда добавляйте description и examples:

```python
from pydantic import BaseModel, Field

class VideoConfig(BaseModel):
    resolution: str = Field(
        "1920x1080",
        description="Разрешение видео",
        examples=["1920x1080", "1280x720", "3840x2160"],
    )
    
    bitrate: int = Field(
        5000,
        gt=0,
        le=50000,
        description="Битрейт в kbps",
        examples=[2500, 5000, 10000],
    )
```

## 🔧 Миграция существующего кода

### Шаг 1: Замените старый Config на model_config

**Было:**
```python
class MyModel(BaseModel):
    name: str
    
    class Config:
        from_attributes = True
```

**Стало:**
```python
from api.schemas.common import ORM_MODEL_CONFIG

class MyModel(BaseModel):
    model_config = ORM_MODEL_CONFIG
    
    name: str
```

### Шаг 2: Замените custom валидаторы на Field constraints

**Было:**
```python
@field_validator("age")
@classmethod
def validate_age(cls, v: int) -> int:
    if v <= 0 or v > 150:
        raise ValueError("Invalid age")
    return v
```

**Стало:**
```python
age: int = Field(..., gt=0, le=150, description="Возраст")
```

### Шаг 3: Используйте общие валидаторы

**Было:**
```python
@field_validator("name")
@classmethod
def validate_name(cls, v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError("Name cannot be empty")
    if len(v) < 3:
        raise ValueError("Name too short")
    return v
```

**Стало:**
```python
from api.schemas.common.validators import strip_and_validate_name

name: str = Field(..., min_length=3, max_length=255)

@field_validator("name", mode="before")
@classmethod
def clean_name(cls, v: str) -> str:
    return strip_and_validate_name(v)
```

## 🚫 Антипаттерны

### ❌ Дублирование валидации

```python
# Плохо - дублирование в каждой схеме
class Schema1(BaseModel):
    @field_validator("name")
    def validate(cls, v): ...

class Schema2(BaseModel):
    @field_validator("name")
    def validate(cls, v): ...  # Та же логика!
```

### ❌ Игнорирование Field constraints

```python
# Плохо - custom валидатор для простых проверок
@field_validator("age")
def check_age(cls, v):
    if v <= 0:
        raise ValueError("Must be positive")
    return v

# Хорошо
age: int = Field(..., gt=0)
```

### ❌ Использование Any без необходимости

```python
# Плохо
data: Any  # Что это? Нет типизации!

# Хорошо
data: dict[str, str] | list[int] | UserData
```

## ✅ Checklist для review

- [ ] Используется `model_config` (не старый `class Config`)
- [ ] Порядок: config → обязательные → опциональные → валидаторы
- [ ] Field constraints вместо custom валидаторов где возможно
- [ ] Используются общие валидаторы из `common.validators`
- [ ] Все поля имеют `description`
- [ ] Нет дублирования валидации
- [ ] Нет `Any` без необходимости
- [ ] Examples добавлены для сложных полей

## 🔗 См. также

- [API_SCHEMAS_GUIDE.md](API_SCHEMAS_GUIDE.md) - общий гайд по схемам
- [Pydantic V2 Docs](https://docs.pydantic.dev/latest/) - официальная документация
