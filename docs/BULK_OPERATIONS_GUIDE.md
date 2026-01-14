# Bulk Operations Guide

**Обработка нескольких записей за раз** через bulk API endpoints.

## Содержание

- [Что такое Bulk Operations](#что-такое-bulk-operations)
- [Архитектура](#архитектура)
- [Доступные операции](#доступные-операции)
- [Режимы выборки](#режимы-выборки)
- [Примеры использования](#примеры-использования)
- [Dry-run режим](#dry-run-режим)
- [Best Practices](#best-practices)

---

## Что такое Bulk Operations

Bulk Operations позволяют запустить обработку для нескольких recordings одновременно.

**Преимущества:**
- ✅ Экономия времени - одним запросом запускаете N задач
- ✅ Автоматическая выборка по фильтрам
- ✅ Унифицированная структура для всех операций
- ✅ Dry-run для проверки перед выполнением

**⚠️ Не путать с Fireworks Batch API:**
- **Bulk Operations** = обработка многих recordings
- **Fireworks Batch API** = режим обработки Fireworks (отложенный для экономии)
- Можно комбинировать: bulk transcribe + Fireworks Batch API

---

## Архитектура

```
POST /api/v1/recordings/bulk/{operation}
↓
Resolve recording_ids (явный список ИЛИ фильтры)
↓
Создать N независимых Celery задач
↓
Вернуть список task_ids для мониторинга
```

**Каждая запись обрабатывается независимо:**
- Одна упала = остальные продолжают работать
- Каждая имеет свой task_id
- Progress tracking через `/api/v1/tasks/{task_id}`

---

## Доступные операции

### 1. Download - Скачивание видео из Zoom

```
POST /api/v1/recordings/bulk/download
```

**Параметры:**
- `force`: Перезаписать уже скачанные (default: false)
- `allow_skipped`: Разрешить скачивание SKIPPED записей (default: false)

**Пример:**
```bash
POST /api/v1/recordings/bulk/download
{
  "recording_ids": [1, 2, 3],
  "force": false
}
```

---

### 2. Trim - Обработка видео (FFmpeg, удаление тишины)

```
POST /api/v1/recordings/bulk/trim
```

**Параметры:**
- `silence_threshold`: Порог тишины в dB (default: -40.0)
- `min_silence_duration`: Минимальная длительность тишины в сек (default: 2.0)
- `padding_before`: Padding до тишины (default: 5.0)
- `padding_after`: Padding после тишины (default: 5.0)

**Пример:**
```bash
POST /api/v1/recordings/bulk/trim
{
  "filters": {
    "status": ["DOWNLOADED"],
    "template_id": 5
  },
  "silence_threshold": -35.0,
  "limit": 50
}
```

---

### 3. Transcribe - Транскрибация

```
POST /api/v1/recordings/bulk/transcribe
```

**Параметры:**
- `use_batch_api`: Использовать Fireworks Batch API для экономии ~50% (default: false)
- `poll_interval`: Интервал polling для Batch API (default: 10.0)
- `max_wait_time`: Максимальное время ожидания для Batch API (default: 3600.0)

**Пример с Fireworks Batch API (экономия ~50%):**
```bash
POST /api/v1/recordings/bulk/transcribe
{
  "filters": {
    "status": ["PROCESSED", "TRIMMED"],
    "is_mapped": true
  },
  "use_batch_api": true,
  "limit": 100
}
```

Подробнее про Fireworks Batch API: [FIREWORKS_BATCH_API.md](./FIREWORKS_BATCH_API.md)

---

### 4. Topics - Извлечение тем

```
POST /api/v1/recordings/bulk/topics
```

**Параметры:**
- `granularity`: Уровень детализации - "short" или "long" (default: "long")
- `version_id`: ID версии (опционально)

**Пример:**
```bash
POST /api/v1/recordings/bulk/topics
{
  "filters": {
    "status": ["TRANSCRIBED"]
  },
  "granularity": "long",
  "limit": 50
}
```

---

### 5. Subtitles - Генерация субтитров

```
POST /api/v1/recordings/bulk/subtitles
```

**Параметры:**
- `formats`: Форматы субтитров (default: ["srt", "vtt"])

**Пример:**
```bash
POST /api/v1/recordings/bulk/subtitles
{
  "recording_ids": [10, 11, 12],
  "formats": ["srt", "vtt"]
}
```

---

### 6. Upload - Загрузка на платформы

```
POST /api/v1/recordings/bulk/upload
```

**Параметры:**
- `platforms`: Список платформ (youtube, vk). Если не указан - из preset
- `preset_id`: ID preset для override (опционально)

**Пример:**
```bash
POST /api/v1/recordings/bulk/upload
{
  "filters": {
    "status": ["TOPICS_EXTRACTED"],
    "is_mapped": true
  },
  "platforms": ["youtube", "vk"],
  "limit": 30
}
```

---

### 7. Process - Полный пайплайн

```
POST /api/v1/recordings/bulk/process
```

**Все этапы:** download → trim → transcribe → topics → upload

**Параметры:**
- `config_override`: Override конфигурации поверх template config
  - `processing_config`: Override обработки (transcription, silence detection)
  - `metadata_config`: Override метаданных (title, description, playlists)
  - `output_config`: Override выгрузки (preset_ids, auto_upload, platforms)

**Пример:**
```bash
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "template_id": 5,
    "status": ["INITIALIZED", "FAILED"],
    "is_mapped": true
  },
  "config_override": {
    "processing_config": {
      "transcription": {
        "granularity": "short",
        "use_batch_api": true
      }
    },
    "output_config": {
      "auto_upload": true,
      "platforms": ["youtube"]
    }
  },
  "limit": 50
}
```

---

## Режимы выборки

Bulk операции поддерживают **два режима выборки** recordings:

### Режим 1: Явный список ID

Указываете конкретные recording_ids:

```json
{
  "recording_ids": [1, 2, 3, 4, 5]
}
```

**Когда использовать:**
- Знаете точные ID
- Выборочная обработка
- Ручной контроль

---

### Режим 2: Автоматическая выборка по фильтрам

Система автоматически выбирает recordings по критериям:

```json
{
  "filters": {
    "template_id": 5,
    "source_id": 10,
    "status": ["INITIALIZED", "FAILED"],
    "is_mapped": true,
    "exclude_blank": true,
    "order_by": "created_at",
    "order": "asc"
  },
  "limit": 50
}
```

**Доступные фильтры:**

| Фильтр | Тип | Описание |
|--------|-----|----------|
| `template_id` | int | Фильтр по ID шаблона |
| `source_id` | int | Фильтр по ID источника |
| `status` | list[str] | Список статусов (INITIALIZED, DOWNLOADED, PROCESSED, TRANSCRIBED, READY, etc.) |
| `is_mapped` | bool | Только записи с mapping к template |
| `failed` | bool | Только failed записи |
| `exclude_blank` | bool | Исключить blank records (default: true) |
| `from_date` | str | Дата начала (ISO 8601) |
| `to_date` | str | Дата окончания (ISO 8601) |
| `order_by` | str | Поле сортировки: created_at, updated_at, id |
| `order` | str | Направление: asc, desc |

**⚠️ Специальный статус "FAILED":**

В системе нет статуса `FAILED` как enum значения - вместо этого используется булевое поле `recording.failed`. Однако в фильтрах вы можете использовать `"FAILED"` как псевдо-статус:

```json
{
  "status": ["FAILED"]  // Фильтрует по recording.failed = true
}
```

Можно комбинировать с обычными статусами:
```json
{
  "status": ["INITIALIZED", "FAILED"]  // INITIALIZED ИЛИ failed=true
}
```

**Лимит:**
- По умолчанию: 50 записей
- Максимум: 200 записей за запрос

**Когда использовать:**
- Массовая обработка
- "Обработать все INITIALIZED"
- "Retry все FAILED"
- "Загрузить все готовые"

---

## Примеры использования

### Сценарий 1: Первичная обработка новых записей

```bash
# 1. Скачать все новые из source
POST /api/v1/recordings/bulk/download
{
  "filters": {
    "source_id": 10,
    "status": ["PENDING"]
  },
  "limit": 50
}

# 2. Обработать скачанные (trim + transcribe + topics + upload)
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "source_id": 10,
    "status": ["DOWNLOADED"],
    "is_mapped": true
  },
  "limit": 50
}
```

---

### Сценарий 2: Retry failed recordings

```bash
# Используйте "FAILED" как псевдо-статус для фильтрации failed записей
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "status": ["FAILED"],  # Фильтрует по recording.failed = true
    "template_id": 5
  },
  "limit": 30
}

# Альтернатива: явное использование failed фильтра
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "failed": true,
    "template_id": 5
  },
  "limit": 30
}
```

---

### Сценарий 3: Массовая транскрибация с экономией

```bash
POST /api/v1/recordings/bulk/transcribe
{
  "filters": {
    "status": ["PROCESSED"],
    "template_id": 5
  },
  "use_batch_api": true,  # Экономия ~50%
  "limit": 100
}
```

---

### Сценарий 4: Выборочная обработка конкретных записей

```bash
POST /api/v1/recordings/bulk/process
{
  "recording_ids": [15, 16, 17, 18],
  "config_override": {
    "output_config": {
      "auto_upload": false  # Не загружать автоматически
    }
  }
}
```

---

### Сценарий 5: Загрузка всех готовых записей

```bash
POST /api/v1/recordings/bulk/upload
{
  "filters": {
    "status": ["TOPICS_EXTRACTED"],
    "is_mapped": true,
    "template_id": 5
  },
  "platforms": ["youtube", "vk"],
  "limit": 50
}
```

---

## Dry-run режим

Для `/process` и `/bulk/process` доступен dry-run режим - проверка перед выполнением.

### Single Recording Dry-run

```bash
POST /api/v1/recordings/123/process?dry_run=true
{
  "config_override": {
    "processing_config": {
      "transcription": {"granularity": "short"}
    }
  }
}
```

**Response:**
```json
{
  "dry_run": true,
  "recording_id": 123,
  "current_status": "DOWNLOADED",
  "steps": [
    {"name": "download", "enabled": false, "skip_reason": "Already downloaded"},
    {"name": "trim", "enabled": true},
    {"name": "transcribe", "enabled": true},
    {"name": "topics", "enabled": true},
    {"name": "upload", "enabled": true, "platforms": ["youtube"]}
  ],
  "warnings": []
}
```

---

### Bulk Dry-run

```bash
POST /api/v1/recordings/bulk/process?dry_run=true
{
  "filters": {
    "template_id": 5,
    "status": ["INITIALIZED"]
  },
  "limit": 50
}
```

**Response:**
```json
{
  "dry_run": true,
  "matched_count": 42,
  "recording_ids": [1, 2, 3, 4, 5, ...],
  "limit_applied": 50
}
```

**Используйте dry-run когда:**
- ✅ Проверить сколько записей попадет под фильтры
- ✅ Убедиться что фильтры правильные
- ✅ Посмотреть какие шаги будут выполнены
- ✅ Избежать случайной массовой обработки

---

## Response Structure

Все bulk операции возвращают единообразную структуру:

```json
{
  "queued_count": 45,
  "skipped_count": 3,
  "error_count": 2,
  "tasks": [
    {
      "recording_id": 1,
      "task_id": "abc-123-def-456",
      "status": "queued",
      "check_status_url": "/api/v1/tasks/abc-123-def-456"
    },
    {
      "recording_id": 2,
      "task_id": null,
      "status": "skipped",
      "reason": "Already processed"
    },
    {
      "recording_id": 3,
      "task_id": null,
      "status": "error",
      "error": "Recording not found"
    }
  ]
}
```

**Проверка прогресса:**
```bash
GET /api/v1/tasks/{task_id}
```

---

## Best Practices

### 1. Используйте фильтры для automation

```bash
# ✅ Хорошо: автоматическая обработка новых
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "status": ["INITIALIZED"],
    "is_mapped": true
  }
}

# ❌ Плохо: ручной поиск ID каждый раз
POST /api/v1/recordings/bulk/process
{
  "recording_ids": [1, 2, 3, ...]  # Нужно каждый раз обновлять
}
```

---

### 2. Используйте Fireworks Batch API для экономии

```bash
# При bulk transcribe ВСЕГДА включайте use_batch_api если нет срочности
POST /api/v1/recordings/bulk/transcribe
{
  "filters": {...},
  "use_batch_api": true  # Экономия ~50%
}
```

---

### 3. Контролируйте лимиты

```bash
# ✅ Хорошо: разумный лимит
{
  "filters": {...},
  "limit": 50
}

# ❌ Плохо: слишком много за раз
{
  "filters": {...},
  "limit": 200  # Может перегрузить систему
}
```

**Рекомендация:** 20-50 записей за раз для тяжелых операций (transcribe, process).

---

### 4. Используйте dry-run перед массовыми операциями

```bash
# 1. Сначала dry-run
POST /api/v1/recordings/bulk/process?dry_run=true
{
  "filters": {"status": ["INITIALIZED"]}
}
# → Вернет: matched_count: 150

# 2. Если слишком много - уточните фильтры
POST /api/v1/recordings/bulk/process?dry_run=true
{
  "filters": {
    "status": ["INITIALIZED"],
    "template_id": 5  # Уточнили
  },
  "limit": 50
}
# → Вернет: matched_count: 42

# 3. Теперь запускаем реально
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "status": ["INITIALIZED"],
    "template_id": 5
  },
  "limit": 50
}
```

---

### 5. Мониторьте задачи

```bash
# Получили task_ids из bulk response
tasks = ["abc-123", "def-456", "ghi-789"]

# Проверяем каждую
for task_id in tasks:
    GET /api/v1/tasks/{task_id}
```

Или используйте автоматизацию для проверки статуса всех задач.

---

### 6. Retry failed с фильтрами

```bash
# Автоматически retry все failed из template
# "FAILED" - это псевдо-статус, фильтрует по recording.failed = true
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "status": ["FAILED"],
    "template_id": 5
  }
}

# Или явно через failed фильтр
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "failed": true,
    "template_id": 5
  }
}
```

---

### 7. Комбинируйте config_override для гибкости

```bash
# Все recordings template #5, но с другим preset
POST /api/v1/recordings/bulk/process
{
  "filters": {
    "template_id": 5,
    "status": ["INITIALIZED"]
  },
  "config_override": {
    "output_config": {
      "preset_ids": {
        "youtube": 10,  # Другой preset
        "vk": 15
      }
    }
  }
}
```

---

## Troubleshooting

### "No recordings matched filters"

**Причина:** Фильтры слишком строгие или нет подходящих записей.

**Решение:**
1. Используйте dry-run для проверки
2. Упростите фильтры
3. Проверьте что recordings существуют: `GET /api/v1/recordings?status=INITIALIZED`

---

### "Too many tasks queued"

**Причина:** Слишком большой limit.

**Решение:**
- Уменьшите limit до 20-50
- Запускайте несколько bulk запросов последовательно

---

### "Some tasks failed"

**Причина:** Индивидуальные ошибки в recordings.

**Решение:**
1. Проверьте статус каждой задачи: `GET /api/v1/tasks/{task_id}`
2. Исправьте проблемы
3. Retry failed: `POST /bulk/process {"filters": {"status": ["FAILED"]}}`

---

## См. также

- [FIREWORKS_BATCH_API.md](./FIREWORKS_BATCH_API.md) - Экономия на транскрибации
- [TEMPLATES.md](./TEMPLATES.md) - Metadata configuration for templates
- [TEMPLATE_REMATCH_FEATURE.md](./TEMPLATE_REMATCH_FEATURE.md) - Template mapping

---

## API Reference

### Base URL
```
https://your-domain.com/api/v1/recordings/bulk/
```

### Authentication
Все bulk endpoints требуют аутентификации через JWT token:

```bash
Authorization: Bearer <your_jwt_token>
```

### Rate Limits
- Celery worker concurrency контролирует параллельность
- Рекомендуется: не более 50-100 задач одновременно
- Для больших объемов используйте несколько запросов

---

**Последнее обновление:** 2026-01-13
