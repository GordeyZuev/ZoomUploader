# API Guide - Pydantic Schemas & Best Practices

**Полное руководство по работе с API схемами**

---

## 📋 Содержание

1. [Schema Architecture](#schema-architecture)
2. [Best Practices](#best-practices)
3. [Common Validators](#common-validators)
4. [Examples](#examples)

---

## Schema Architecture

### Структура

```
api/schemas/
├── common/              # Базовые переиспользуемые схемы
│   ├── responses.py     # MessageResponse, TaskQueuedResponse
│   ├── validators.py    # Общие валидаторы
├── auth/                # Аутентификация
├── credentials/         # Credentials management
├── recording/           # Recordings
├── template/            # Templates, Presets, Sources (полностью типизированные)
│   ├── template.py
│   ├── output_preset.py
│   ├── input_source.py
│   ├── matching_rules.py
│   ├── processing_config.py
│   ├── metadata_config.py
│   └── preset_metadata.py
```

### Fully Typed Schemas

**Templates, Presets, Sources - полностью типизированы:**

```python
from api.schemas.template import RecordingTemplateCreate

template = RecordingTemplateCreate(
    name="ML Lectures",
    matching_rules={
        "keywords": ["ML", "AI"],
        "match_mode": "any"
    },
    processing_config={
        "transcription": {
            "enable_transcription": True,
            "language": "ru"
        }
    },
    metadata_config={
        "title_template": "{themes}",
        "youtube": {
            "playlist_id": "PLxxx",
            "privacy": "unlisted"
        }
    }
)
```

**Преимущества:**
- ✅ Full autocompletion в IDE
- ✅ Type checking на всех уровнях
- ✅ OpenAPI/Swagger documentation
- ✅ Runtime validation

---

## Best Practices

### 1. Используйте Field constraints (не validators)

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

### 2. Built-in constraints

```python
from pydantic import BaseModel, Field

class User(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    age: int = Field(..., gt=0, le=150)
    email: str = Field(..., pattern=r'^[\w\.-]+@[\w\.-]+\.\w+$')
    tags: list[str] = Field(default_factory=list, max_items=10)
```

**Constraints:**
- `min_length`, `max_length` - для строк
- `gt`, `ge`, `lt`, `le` - для чисел
- `pattern` - regex для строк
- `min_items`, `max_items` - для списков

### 3. ConfigDict для порядка полей

```python
from pydantic import BaseModel, ConfigDict

class MyModel(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "title": "My Model",
            "description": "Model description"
        }
    )
    
    # Порядок сохранится в Swagger
    id: int
    name: str
    created_at: datetime
```

### 4. Custom validators (только когда нужно)

**Используйте только для сложной логики:**

```python
from pydantic import field_validator

class Template(BaseModel):
    keywords: list[str]
    
    @field_validator("keywords", mode="before")
    @classmethod
    def normalize_keywords(cls, v):
        # Сложная логика преобразования
        if isinstance(v, str):
            return [k.strip() for k in v.split(",")]
        return v
```

**mode="before"** - для preprocessing данных

### 5. Computed fields

```python
from pydantic import computed_field

class Recording(BaseModel):
    start_time: datetime
    end_time: datetime
    
    @computed_field
    @property
    def duration_minutes(self) -> int:
        return int((self.end_time - self.start_time).total_seconds() / 60)
```

### 6. Наследование schemas

```python
# Base schema
class RecordingBase(BaseModel):
    display_name: str
    start_time: datetime

# Create schema (input)
class RecordingCreate(RecordingBase):
    source_id: int

# Response schema (output)
class RecordingResponse(RecordingBase):
    id: int
    status: str
    created_at: datetime
```

---

## Common Validators

### URL Validator

```python
from pydantic import HttpUrl, field_validator

class Config(BaseModel):
    webhook_url: HttpUrl | None = None
    
    @field_validator("webhook_url", mode="before")
    @classmethod
    def empty_str_to_none(cls, v):
        return None if v == "" else v
```

### Email Validator

```python
from pydantic import EmailStr

class User(BaseModel):
    email: EmailStr  # Built-in validation
```

### Datetime Validator

```python
from datetime import datetime
from pydantic import field_validator

class Event(BaseModel):
    start_time: datetime
    end_time: datetime
    
    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, v, info):
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v
```

### JSON Field Validator

```python
@field_validator("config", mode="before")
@classmethod
def parse_json_string(cls, v):
    if isinstance(v, str):
        return json.loads(v)
    return v
```

---

## Examples

### Template Create Schema

```python
from api.schemas.template import RecordingTemplateCreate

template_data = {
    "name": "ML Lectures",
    "matching_rules": {
        "keywords": ["ML", "Machine Learning"],
        "patterns": ["Лекция \\d+:.*ML"],
        "source_ids": [1],
        "match_mode": "any"
    },
    "processing_config": {
        "transcription": {
            "enable_transcription": True,
            "language": "ru",
            "enable_topics": True,
            "granularity": "long"
        },
        "video_processing": {
            "extract_audio": True,
            "compress_audio": True,
            "target_bitrate": "32k"
        }
    },
    "metadata_config": {
        "title_template": "МО | {themes}",
        "youtube": {
            "playlist_id": "PLxxx",
            "privacy": "unlisted",
            "category_id": 27
        }
    },
    "output_config": {
        "preset_ids": [1, 2],
        "auto_upload": True
    }
}

template = RecordingTemplateCreate(**template_data)
```

### Preset Create Schema

```python
from api.schemas.template import OutputPresetCreate

preset_data = {
    "name": "YouTube Main",
    "platform": "youtube",
    "is_active": True,
    "metadata": {
        "playlist_id": "PLxxx",
        "privacy": "unlisted",
        "category_id": 27,
        "tags": ["ML", "AI", "Education"],
        "made_for_kids": False
    }
}

preset = OutputPresetCreate(**preset_data)
```

### Recording Create

```python
from api.schemas.recording import RecordingCreate

recording = RecordingCreate(
    display_name="ML Lecture 1",
    source_id=1,
    config_override={
        "transcription": {
            "language": "en"  # Override template
        }
    }
)
```

---

## Response Schemas

### Standard Success

```python
from api.schemas.common import MessageResponse

MessageResponse(
    message="Template created successfully",
    data={"template_id": 5}
)
```

### Task Queued

```python
from api.schemas.common import TaskQueuedResponse

TaskQueuedResponse(
    task_id="abc-123",
    status="queued",
    message="Processing started"
)
```

### Bulk Operation

```python
from api.schemas.common import BulkOperationResponse

BulkOperationResponse(
    total=100,
    success=95,
    failed=5,
    task_ids=["task-1", "task-2", "..."],
    message="Bulk operation completed"
)
```

---

## Validation Errors

**Pydantic автоматически генерирует детальные ошибки:**

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["body", "age"],
      "msg": "Input should be a valid integer",
      "input": "abc"
    },
    {
      "type": "string_too_short",
      "loc": ["body", "username"],
      "msg": "String should have at least 3 characters",
      "input": "ab"
    }
  ]
}
```

---

## Pydantic V2 Migration

### Основные изменения

**1. model_config вместо Config:**
```python
# V1
class Model(BaseModel):
    class Config:
        from_attributes = True

# V2
class Model(BaseModel):
    model_config = ConfigDict(from_attributes=True)
```

**2. field_validator вместо validator:**
```python
# V1
@validator("field")
def validate_field(cls, v):
    return v

# V2
@field_validator("field")
@classmethod
def validate_field(cls, v):
    return v
```

**3. Field constraints:**
```python
# V1
Field(..., min_length=3)

# V2 (то же самое)
Field(..., min_length=3)
```

---

---

## Admin & Quota API

### User Quota Endpoints

**GET /api/v1/users/me/quota** - Get user quota status

```json
{
  "subscription": {
    "plan": {
      "name": "free",
      "included_recordings_per_month": 10,
      "included_storage_gb": 5,
      "max_concurrent_tasks": 1,
      "max_automation_jobs": 0
    },
    "effective_max_recordings_per_month": 10,
    "effective_max_storage_gb": 5
  },
  "usage": {
    "recordings_this_month": 5,
    "storage_used_gb": 2.3,
    "storage_used_bytes": 2469606195,
    "concurrent_tasks": 0
  },
  "limits": {
    "recordings_remaining": 5,
    "storage_remaining_gb": 2.7,
    "can_create_recording": true,
    "can_upload_file": true,
    "can_run_task": true
  }
}
```

**GET /api/v1/users/me/quota/usage-history** - Monthly usage history

```json
{
  "current_month": {
    "month": "2026-01",
    "recordings_created": 5,
    "storage_used_gb": 2.3
  },
  "history": [
    {"month": "2025-12", "recordings_created": 8, "storage_used_gb": 3.1},
    {"month": "2025-11", "recordings_created": 10, "storage_used_gb": 4.5}
  ]
}
```

### Admin Endpoints

**GET /api/v1/admin/stats** - System-wide statistics (admin only)

```json
{
  "total_users": 50,
  "active_users": 35,
  "total_recordings": 1250,
  "total_storage_gb": 125.5,
  "tasks_queued": 5,
  "tasks_running": 3,
  "subscription_stats": {
    "free": 40,
    "basic": 8,
    "pro": 2
  }
}
```

**GET /api/v1/admin/users** - List all users (admin only)

**PATCH /api/v1/admin/users/{id}/quota** - Update user quota (admin only)

```bash
curl -X PATCH /api/v1/admin/users/5/quota \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{
    "custom_max_recordings_per_month": 50,
    "custom_max_storage_gb": 20
  }'
```

### Quota Middleware

**Automatic quota checks:**
- POST /recordings → check `can_create_recording`
- POST /upload → check `can_upload_file`
- POST /bulk/* → check `can_run_task`

**Response (quota exceeded):**
```json
{
  "detail": "Monthly recording limit reached (10/10)",
  "error_type": "quota_exceeded",
  "upgrade_url": "/plans"
}
```

---

## См. также

- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - API Design principles
- [TECHNICAL.md](TECHNICAL.md) - REST API endpoints
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - Bulk API

---

**Документ обновлен:** Январь 2026  
**Pydantic Version:** V2 ✅
