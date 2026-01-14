# Template Re-match Feature

## 🎯 Проблема

**Типичный сценарий:**
1. Sync recordings → получают `SKIPPED` статус (нет template)
2. Пользователь создаёт template позже
3. **Старые recordings остаются SKIPPED!**

**Решение:** Автоматический и ручной re-match recordings к templates.

## ✨ Функциональность

### 1. Автоматический Re-match (по умолчанию)

При создании нового template **автоматически** запускается background task:
- Проверяет все SKIPPED recordings
- Находит те, что matched к новому template
- Обновляет `is_mapped=True`, `template_id`, `status=INITIALIZED`

### 1.1. Автоматический Unmap при удалении

При удалении template **автоматически** происходит unmap всех связанных recordings:
- Все recordings с этим `template_id` → `template_id=NULL`, `is_mapped=False`
- Status recordings НЕ меняется (DOWNLOADED остаётся DOWNLOADED, UPLOADED остаётся UPLOADED)
- Recordings становятся доступны для нового matching

**Симметричное поведение:**
- ✅ **Создание template** → auto-rematch SKIPPED recordings
- ✅ **Удаление template** → auto-unmap всех связанных recordings

```bash
POST /api/v1/templates
{
  "name": "ИИ Course",
  "matching_rules": {"keywords": ["ИИ_1 курс"]},
  "processing_config": {...},
  "output_config": {"preset_ids": [1, 2]}
}

# Автоматически запускается background task!
# Все SKIPPED recordings с "ИИ_1 курс" → INITIALIZED
```

**Можно отключить:**
```bash
POST /api/v1/templates?auto_rematch=false
```

### 2. Preview Re-match (безопасно)

Показать что будет matched **БЕЗ изменений**:

```bash
POST /api/v1/templates/{id}/preview-rematch
?only_unmapped=true
&limit=100
```

**Response:**
```json
{
  "template_id": 1,
  "template_name": "ИИ Course",
  "total_checked": 50,
  "will_match_count": 12,
  "will_match": [
    {
      "id": 44,
      "display_name": "ИИ_1 курс_Анализ временных рядов",
      "current_status": "SKIPPED",
      "will_become_status": "INITIALIZED",
      "start_time": "2025-12-11T15:05:22+00:00"
    }
  ]
}
```

### 3. Manual Re-match (контроль)

Вручную запустить re-match:

```bash
POST /api/v1/templates/{id}/rematch
?only_unmapped=true
```

**Use cases:**
- После изменения `matching_rules`
- Периодическая проверка unmapped recordings
- Re-match конкретного template

**Response:**
```json
{
  "message": "Re-match task queued successfully",
  "task_id": "abc-123-def",
  "template_id": 1,
  "template_name": "ИИ Course",
  "note": "Use GET /api/v1/tasks/{task_id} to check status"
}
```

**Проверка статуса:**
```bash
GET /api/v1/tasks/abc-123-def
```

**Result:**
```json
{
  "task_id": "abc-123-def",
  "status": "completed",
  "result": {
    "success": true,
    "checked": 50,
    "matched": 12,
    "updated": 12,
    "recordings": [44, 45, 46, ...]
  }
}
```

## 📊 Параметры

### `only_unmapped` (default: `true`)

**`true`** - проверять только SKIPPED recordings:
- Быстрее
- Безопаснее (не трогает уже mapped recordings)
- **Рекомендуется** для большинства случаев

**`false`** - проверять ВСЕ recordings:
- Медленнее
- Может перезаписать `template_id` у уже mapped recordings
- Используйте осторожно!

### `auto_rematch` (default: `true`)

**`true`** - автоматический re-match при создании template:
- Удобно
- Сразу после создания template все recordings готовы
- **Рекомендуется**

**`false`** - не запускать автоматический re-match:
- Требует ручного re-match
- Полезно для тестирования или draft templates

### `limit` (preview only, default: `100`, max: `500`)

Максимум recordings для проверки в preview:
- Ограничивает нагрузку
- Достаточно для понимания что будет matched

## 🚀 Workflows

### Workflow 1: Создать Template (автоматический re-match)

```bash
# 1. Создать template
POST /api/v1/templates
{
  "name": "ML Course",
  "matching_rules": {"keywords": ["Machine Learning"]},
  ...
}

# 2. Автоматически запускается background task
# Статус: все SKIPPED с "Machine Learning" → INITIALIZED

# 3. Проверить unmapped
GET /api/v1/recordings/unmapped
# Должно быть меньше recordings
```

### Workflow 2: Preview перед Apply (осторожный подход)

```bash
# 1. Preview что будет matched
POST /api/v1/templates/1/preview-rematch

# 2. Проверить results
# Если всё ок → apply

# 3. Apply re-match
POST /api/v1/templates/1/rematch

# 4. Проверить task status
GET /api/v1/tasks/{task_id}
```

### Workflow 3: После изменения matching_rules

```bash
# 1. Обновить template
PATCH /api/v1/templates/1
{
  "matching_rules": {
    "keywords": ["новые", "ключевые", "слова"]
  }
}

# 2. Preview новый matching
POST /api/v1/templates/1/preview-rematch

# 3. Apply re-match
POST /api/v1/templates/1/rematch
```

### Workflow 4: Периодическая проверка unmapped

```bash
# 1. Проверить unmapped recordings
GET /api/v1/recordings/unmapped

# 2. Создать template для них
POST /api/v1/templates/from-recording/{id}

# 3. Автоматический re-match запустится
# Или вручную:
POST /api/v1/templates/{id}/rematch
```

### Workflow 5: Удаление template (auto-unmap)

```bash
# 1. Проверить сколько recordings mapped к template
GET /api/v1/templates/1
# Response: "used_count": 15

# 2. Удалить template
DELETE /api/v1/templates/1

# 3. Автоматически unmapped 15 recordings
# Логи: "Unmapped 15 recordings from template 1 'Course Name'"

# 4. Проверить что recordings unmapped
GET /api/v1/recordings?mapped=false
# Должно быть +15 recordings
```

## 🔐 Безопасность

### Safe by Default

1. **Только unmapped по умолчанию** - не трогает уже mapped recordings
2. **Preview доступен** - можно проверить перед применением
3. **Background task** - не блокирует API
4. **Проверка is_active** - не работает с inactive/draft templates

### Что обновляется

Re-match обновляет **только unmapped recordings**:

**ДО:**
```json
{
  "id": 44,
  "status": "SKIPPED",
  "is_mapped": false,
  "template_id": null
}
```

**ПОСЛЕ:**
```json
{
  "id": 44,
  "status": "INITIALIZED",
  "is_mapped": true,
  "template_id": 1
}
```

### Что НЕ обновляется

- ✅ Уже mapped recordings (если `only_unmapped=true`)
- ✅ Recordings в статусе DOWNLOADED, PROCESSED, UPLOADED и т.д.
- ✅ Recordings с `failed=true`

## 📈 Performance

### Оптимизации

1. **Batch loading** - все recordings загружаются одним запросом
2. **Async processing** - background task, не блокирует API
3. **Progress updates** - можно отслеживать прогресс через task status
4. **Pagination в preview** - ограничение `limit` для быстрого preview

### Ожидаемая производительность

| Recordings | Время (примерно) |
|------------|------------------|
| 100        | ~5 сек           |
| 1,000      | ~30 сек          |
| 10,000     | ~5 мин           |

**Note:** Зависит от сложности matching rules (regex медленнее keywords).

## 🧪 Testing

### Test Scenarios

**1. Auto re-match при создании template:**
```bash
# Создать SKIPPED recordings
# Создать template
# Проверить что recordings → INITIALIZED
```

**2. Preview без изменений:**
```bash
# Preview re-match
# Проверить что данные НЕ изменились
# Apply re-match
# Проверить что данные изменились
```

**3. Re-match после изменения rules:**
```bash
# Создать template с rules A
# Обновить rules на B
# Re-match
# Проверить что matched правильные recordings
```

**4. Only unmapped защита:**
```bash
# Создать mapped recording с template_id=1
# Re-match с template_id=2 и only_unmapped=true
# Проверить что template_id остался 1
```

## 🎓 Best Practices

### DO ✅

- ✅ Используйте preview перед apply
- ✅ Используйте `only_unmapped=true` для безопасности
- ✅ Проверяйте task status после re-match
- ✅ Периодически проверяйте unmapped recordings
- ✅ Создавайте templates с чёткими matching rules

### DON'T ❌

- ❌ Не используйте `only_unmapped=false` без необходимости
- ❌ Не создавайте слишком широкие matching rules (может matched всё)
- ❌ Не забывайте про preview перед re-match большого количества recordings
- ❌ Не запускайте несколько re-match tasks одновременно для одного template

## 📚 API Reference

### POST /api/v1/templates

**Query params:**
- `auto_rematch` (bool, default: `true`) - запустить автоматический re-match

### DELETE /api/v1/templates/{id}

**Behavior:**
- Автоматически unmaps все recordings с этим template
- Обновляет `template_id → NULL`, `is_mapped → False`
- Status recordings не меняется
- Логирует количество unmapped recordings

**Response:** `204 No Content`

### POST /api/v1/templates/{id}/preview-rematch

**Query params:**
- `only_unmapped` (bool, default: `true`)
- `limit` (int, default: 100, max: 500)

**Response:**
```json
{
  "template_id": int,
  "template_name": string,
  "total_checked": int,
  "will_match_count": int,
  "will_match": [...],
  "note": string
}
```

### POST /api/v1/templates/{id}/rematch

**Query params:**
- `only_unmapped` (bool, default: `true`)

**Response:**
```json
{
  "message": string,
  "task_id": string,
  "template_id": int,
  "template_name": string,
  "note": string
}
```

### GET /api/v1/tasks/{task_id}

**Response:**
```json
{
  "task_id": string,
  "status": "completed" | "processing" | "failed",
  "result": {
    "success": bool,
    "checked": int,
    "matched": int,
    "updated": int,
    "recordings": [int]
  }
}
```

---

**Status:** ✅ Production-Ready  
**Date:** 11.01.2026

