# API Schemas Guide - Руководство по Pydantic схемам

## Обзор

Все API эндпоинты используют Pydantic схемы для валидации входных и выходных данных.

### Архитектура схем

```
api/schemas/
├── common/              # Базовые переиспользуемые схемы
│   ├── responses.py     # MessageResponse, TaskQueuedResponse, BulkOperationResponse
│   ├── health.py        # HealthCheckResponse
│   ├── errors.py        # ErrorResponse, ErrorDetail
│   └── validators.py    # Общие валидаторы для переиспользования
├── task/                # Схемы для Celery задач
│   └── status.py        # TaskStatusResponse, TaskResult, TaskCancelResponse
├── auth/                # Аутентификация
│   ├── user.py          # UserCreate, UserResponse
│   ├── token.py         # TokenPair
│   └── operations.py    # LogoutResponse
├── credentials/         # Управление credentials
│   ├── request.py       # CredentialCreateRequest
│   ├── response.py      # CredentialResponse
│   └── vk_token.py      # VKTokenSubmitRequest
├── recording/           # Записи
│   ├── request.py       # BulkDownloadRequest, etc
│   ├── response.py      # RecordingResponse
│   └── operations.py    # RecordingOperationResponse
├── template/            # Шаблоны, источники, пресеты (полностью типизированные)
│   ├── template.py      # RecordingTemplateCreate, RecordingTemplateResponse
│   ├── output_preset.py # OutputPresetCreate, OutputPresetResponse
│   ├── input_source.py  # InputSourceCreate, InputSourceResponse
│   ├── matching_rules.py     # MatchingRules
│   ├── processing_config.py  # TemplateProcessingConfig
│   ├── metadata_config.py    # TemplateMetadataConfig
│   ├── output_config.py      # TemplateOutputConfig
│   ├── preset_metadata.py    # YouTubePresetMetadata, VKPresetMetadata
│   └── source_config.py      # ZoomSourceConfig, GoogleDriveSourceConfig, etc
└── [other domains]
```

## 📖 Полностью типизированные схемы

Все схемы для Templates, Presets и Sources **полностью типизированы** на всех уровнях вложенности:

### Пример использования

```python
from api.schemas.template import (
    RecordingTemplateCreate,
    MatchingRules,
    TemplateProcessingConfig,
    TemplateMetadataConfig,
    TemplateOutputConfig,
)

template = RecordingTemplateCreate(
    name="Курс ИИ",
    matching_rules=MatchingRules(  # Типизированная модель
        keywords=["ML", "AI"],
        source_ids=[1, 2],
        match_mode="any",
    ),
    processing_config=TemplateProcessingConfig(  # Типизированная модель
        transcription={
            "enable_transcription": True,
            "language": "ru",
            "enable_topics": True,
            "granularity": "long",
            "enable_subtitles": True,
        }
    ),
    metadata_config=TemplateMetadataConfig(  # Типизированная модель
        title_template="МО | {themes}",
        youtube={"playlist_id": "PLxxx...", "privacy": "unlisted"},
    ),
    output_config=TemplateOutputConfig(  # Типизированная модель
        preset_ids=[1],
        auto_upload=True,
    ),
)
```

**Преимущества:**
- ✅ Полный автокомплит в IDE
- ✅ Строгая типизация на всех уровнях
- ✅ Валидация вложенных полей
- ✅ Отличная OpenAPI документация
- ✅ Невозможно сделать опечатку
- ✅ Compile-time проверка типов (mypy, pyright)
- ✅ DRY принцип - переиспользование валидаторов
- ✅ Централизованная валидация через `api.schemas.common.validators`

## 🛠️ Общие валидаторы и конфигурации

### Валидаторы

Для избежания дублирования кода все базовые валидаторы вынесены в `api/schemas/common/validators.py`:

```python
from api.schemas.common.validators import (
    strip_and_validate_name,  # Очистка названий (используйте с Field constraints)
    validate_regex_pattern,   # Валидация одиночного regex паттерна
    validate_regex_patterns,  # Валидация списка regex паттернов
    clean_string_list,        # Очистка списков строк
)
```

**Рекомендация:** Используйте встроенные Field constraints Pydantic вместо custom валидаторов где возможно:
- `Field(min_length=3, max_length=255)` вместо валидации длины
- `Field(gt=0)` вместо валидации положительных чисел
- `Field(pattern=r"regex")` для валидации формата строки

### Конфигурации моделей

Для сохранения порядка полей в Swagger UI используйте общие конфигурации:

```python
from pydantic import BaseModel
from api.schemas.common import BASE_MODEL_CONFIG, ORM_MODEL_CONFIG

class MyRequestSchema(BaseModel):
    model_config = BASE_MODEL_CONFIG  # Сохранит порядок полей
    
    # Поля будут в таком порядке в Swagger UI
    name: str
    description: str | None
    created_at: datetime

class MyResponseSchema(BaseModel):
    model_config = ORM_MODEL_CONFIG  # from_attributes + порядок полей
    
    id: int
    name: str
```

**Важно:** Порядок полей в Swagger UI будет соответствовать порядку определения в классе (не по алфавиту)!

## 📚 Примеры использования

### Output Preset (YouTube)

```python
from api.schemas.template import (
    OutputPresetCreate,
    YouTubePresetMetadata,
    YouTubePrivacy,
    TopicsDisplayFormat,
)

preset = OutputPresetCreate(
    name="YouTube Лекции Public",
    description="Для публичных образовательных видео",
    platform="youtube",
    credential_id=1,
    preset_metadata=YouTubePresetMetadata(
        privacy=YouTubePrivacy.PUBLIC,
        category_id="27",  # Education
        made_for_kids=False,
        embeddable=True,
        license="youtube",
        topics_display={
            "enabled": True,
            "format": TopicsDisplayFormat.NUMBERED_LIST,
            "max_count": 10,
            "prefix": "Темы лекции:",
        },
        disable_comments=False,
        notify_subscribers=True,
    ),
)
```

### Output Preset (VK)

```python
from api.schemas.template import (
    OutputPresetCreate,
    VKPresetMetadata,
    VKPrivacyLevel,
)

preset = OutputPresetCreate(
    name="VK Группа Курсы",
    platform="vk",
    credential_id=2,
    preset_metadata=VKPresetMetadata(
        privacy_view=VKPrivacyLevel.ALL,  # Все могут смотреть
        privacy_comment=VKPrivacyLevel.ALL,  # Все могут комментировать
        group_id=123456,
        topics_display={
            "format": TopicsDisplayFormat.BULLET_LIST,
            "max_count": 8,
        },
        disable_comments=False,
    ),
)
```

### Recording Template (полная)

```python
from api.schemas.template import (
    RecordingTemplateCreate,
    MatchingRules,
    TemplateProcessingConfig,
    TemplateMetadataConfig,
    TemplateOutputConfig,
)

template = RecordingTemplateCreate(
    name="Курс Машинное Обучение 2025",
    description="Автоматическая обработка лекций по ML",
    is_draft=False,
    
    # Правила сопоставления
    matching_rules=MatchingRules(
        keywords=["машинное обучение", "ML", "deep learning"],
        patterns=["^Лекция \\d+", "МО.*202[56]"],
        source_ids=[1, 2],
        match_mode="any",  # OR логика
        case_sensitive=False,
    ),
    
    # Настройки обработки
    processing_config=TemplateProcessingConfig(
        transcription={
            "enable_transcription": True,
            "model": "fireworks",
            "language": "ru",
            "use_batch_api": False,
            "prompt": "Лекция по машинному обучению",
        },
        topics={
            "enable_topics": True,
            "model": "deepseek",
            "granularity": "long",
            "max_topics": 10,
            "min_topic_length": 10,
        },
        subtitles={
            "enable_subtitles": True,
            "formats": ["srt", "vtt"],
            "max_line_length": 80,
        },
        video={
            "enable_processing": True,
            "silence_threshold": -40.0,
            "min_silence_duration": 2.0,
        },
    ),
    
    # Content metadata
    metadata_config=TemplateMetadataConfig(
        title_template="МО | {themes}",
        description_template="Лекция по машинному обучению\n\n{topics_list}\n\nЗаписано: {record_time:DD.MM.YYYY}",
        playlist_id="PLmA-1xX7IuzDK0OSCArxNjG_VDuYOXxTs",
        thumbnail_path="ml_course.png",
        tags=["машинное обучение", "python", "AI"],
        topics_display={
            "format": "bullet_list",
            "max_count": 8,
        },
    ),
    
    # Output настройки
    output_config=TemplateOutputConfig(
        preset_ids=[1, 2],  # Несколько пресетов
        auto_upload=True,
        upload_captions=True,
    ),
)
```

### Input Source (Zoom)

```python
from api.schemas.template import (
    InputSourceCreateValidated,
    ZoomSourceConfig,
)

source = InputSourceCreateValidated(
    name="Zoom ML Lectures 2025",
    description="Zoom recordings для курса ML",
    platform="ZOOM",
    credential_id=1,
    config=ZoomSourceConfig(
        user_id="abc123xyz",
        include_trash=False,
        recording_type="cloud",
    ),
)
```

### Input Source (Google Drive)

```python
from api.schemas.template import (
    InputSourceCreate,
    GoogleDriveSourceConfig,
)

source = InputSourceCreate(
    name="Google Drive ML Storage",
    platform="GOOGLE_DRIVE",
    credential_id=2,
    config=GoogleDriveSourceConfig(
        folder_id="1abc...xyz",
        recursive=True,
        file_pattern=".*\\.mp4$",
    ),
)
```

## 🔍 Доступные вложенные модели

### Matching Rules

```python
from api.schemas.template import MatchingRules

rules = MatchingRules(
    exact_matches=["Название лекции 1"],
    keywords=["ML", "AI"],
    patterns=["^Лекция \\d+"],
    source_ids=[1, 2, 3],
    match_mode="any",  # "any" или "all"
    case_sensitive=False,
)
```

### Processing Config

```python
from api.schemas.template import (
    TemplateProcessingConfig,
    TranscriptionProcessingConfig,
)

processing = TemplateProcessingConfig(
    transcription=TranscriptionProcessingConfig(
        enable_transcription=True,
        language="ru",
        prompt="Лекция по машинному обучению",
        enable_topics=True,
        granularity="long",
        enable_subtitles=True,
    ),
)
```

**Примечание:** `TranscriptionProcessingConfig` содержит объединенные настройки для транскрибации, извлечения тем и субтитров (историческая плоская структура).

### Metadata Config

```python
from api.schemas.template import (
    TemplateMetadataConfig,
    YouTubeMetadataConfig,
    VKMetadataConfig,
    TopicsDisplayConfig,
)

metadata = TemplateMetadataConfig(
    title_template="Курс | {themes}",
    youtube=YouTubeMetadataConfig(
        playlist_id="PLxxx...",
        privacy="unlisted",
        thumbnail_path="media/thumbnails/course.png",
    ),
    vk=VKMetadataConfig(
        album_id="62",
        thumbnail_path="media/thumbnails/course.png",
    ),
    topics_display=TopicsDisplayConfig(
        enabled=True,
        format="numbered_list",
        max_count=10,
    ),
)
```

### Output Config

```python
from api.schemas.template import TemplateOutputConfig

output = TemplateOutputConfig(
    preset_ids=[1, 2, 3],
    auto_upload=True,
    upload_captions=True,
)
```

## ✅ Преимущества типизированных схем

1. **Автокомплит в IDE** - все поля типизированы на всех уровнях
2. **Валидация Pydantic** - автоматическая проверка типов и ограничений
3. **OpenAPI документация** - полная схема в Swagger UI
4. **Enum'ы** - для privacy, format, model и других опций
5. **Field constraints** - min/max length, range, regex
6. **Cross-field валидация** - проверка зависимостей между полями
7. **Clear error messages** - понятные сообщения об ошибках

## 🎯 Best Practices

### DO ✅

- ✅ Используйте типизированные схемы для всех конфигураций
- ✅ Используйте Enum'ы для известных значений (`YouTubePrivacy`, `VKPrivacyLevel`, `TopicsDisplayFormat`)
- ✅ Добавляйте description к полям для документации
- ✅ Используйте examples в Config для OpenAPI
- ✅ Валидируйте зависимости через `model_validator`
- ✅ Переиспользуйте общие валидаторы из `api.schemas.common.validators`
- ✅ Используйте `field_validator` для специфичной логики валидации

### DON'T ❌

- ❌ Не добавляйте `| dict` к типизированным Union'ам
- ❌ Не дублируйте валидацию (DRY) - используйте общие валидаторы
- ❌ Не добавляйте поля "на будущее" (YAGNI)
- ❌ Не оставляйте устаревшие поля в схемах
- ❌ Не используйте `Any` без необходимости - типизируйте все
- ❌ Не делайте слишком глубокую вложенность (KISS)

## 📊 Статистика схем

- **100+ моделей** в OpenAPI
- **71+ эндпоинт** с response_model
- **15+ вложенных типизированных моделей**
- **6 Enum'ов** для опций (`YouTubePrivacy`, `YouTubeLicense`, `VKPrivacyLevel`, `TopicsDisplayFormat`)
- **Полная типизация** на всех уровнях вложенности
- **DRY принцип**: общие валидаторы в `api.schemas.common.validators`
- **Нет дублирования** валидации name, regex паттернов
- **Удалены устаревшие поля**: `is_private`, `watch_directory`

## 📝 Changelog

### 2026-01-14 - Рефакторинг по DRY/YAGNI

- ✅ Создан модуль `api/schemas/common/validators.py` с общими валидаторами
- ✅ Удалено дублирование валидации `name` (было в 4+ местах)
- ✅ Удалено дублирование валидации regex паттернов (было в 3+ местах)
- ✅ Типизированы ранее слабо типизированные поля:
  - `BulkOperationResponse.tasks` → `list[TaskInfo]`
  - `ErrorResponse.detail` → `list[ErrorDetail]`
  - `TaskStatusResponse.result` → `TaskResult | dict`
- ✅ Удалены устаревшие поля:
  - `VKPresetMetadata.is_private` (используйте `privacy_view`)
  - `LocalFileSourceConfig.watch_directory` (не реализовано)
- ✅ Удалено `| dict` из `SourceConfig` - теперь только типизированные конфиги
- ✅ Обновлена документация - удалены упоминания несуществующих схем

## 🔗 См. также

- [PYDANTIC_BEST_PRACTICES.md](PYDANTIC_BEST_PRACTICES.md) - **Best practices работы с Pydantic** (валидаторы, Field constraints, порядок полей)
- [PRESET_METADATA_GUIDE.md](PRESET_METADATA_GUIDE.md) - детальная документация по preset metadata
- [TEMPLATE_MAPPING_ARCHITECTURE.md](TEMPLATE_MAPPING_ARCHITECTURE.md) - архитектура template matching
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - bulk операции и фильтры
