# Templates & Matching System

**Полное руководство по template-driven automation**

**Статус:** ✅ Production Ready

---

## 📋 Содержание

1. [Overview](#overview)
2. [Template Matching](#template-matching)
3. [Re-match Functionality](#re-match-functionality)
4. [Architecture & Future](#architecture--future)
5. [API Reference](#api-reference)

---

## Overview

### Что такое Templates

**Recording Template** - это правила автоматической обработки для определенного типа видео.

**Состоит из:**
- **Matching Rules** - правила сопоставления (keywords, patterns, exact matches)
- **Processing Config** - настройки обработки (transcription, video processing)
- **Metadata Config** - настройки метаданных (title_template, description_template)
- **Output Config** - настройки загрузки (preset_ids, auto_upload)

### Как это работает

```
┌─────────────────────────────────────────┐
│        Template-driven Flow             │
└─────────────────────────────────────────┘

1. Sync recording from source (Zoom, etc.)
    ↓
2. Match against templates (keywords, patterns)
    ↓
3. Set recording.template_id (first match)
    ↓
4. Apply template config automatically
    ↓
5. Process → Transcribe → Upload
```

### Преимущества

- ✅ **Автоматизация:** Новые записи auto-matched и обработаны
- ✅ **Консистентность:** Одинаковые настройки для типа контента
- ✅ **Масштабируемость:** Сотни записей обрабатываются автоматически
- ✅ **Гибкость:** Per-recording overrides если нужно

---

## Template Matching

### Matching Rules

**Структура:**
```json
{
  "exact_matches": ["Lecture: Machine Learning", "AI Course"],
  "keywords": ["ML", "AI", "neural networks"],
  "patterns": ["Лекция \\d+:.*ML", "\\[МО\\].*"],
  "source_ids": [1, 3],
  "match_mode": "any"  // "any" or "all"
}
```

**Типы правил:**

1. **exact_matches** - точное совпадение `display_name`
2. **keywords** - ключевые слова (case-insensitive, substring match)
3. **patterns** - regex паттерны
4. **source_ids** - filter по источникам (опционально)
5. **match_mode:**
   - `"any"` - любое правило сработало → match
   - `"all"` - все правила должны сработать

### Matching Algorithm

```python
def matches_template(recording: Recording, template: Template) -> bool:
    rules = template.matching_rules
    results = []
    
    # Check exact matches
    if rules.exact_matches:
        results.append(recording.display_name in rules.exact_matches)
    
    # Check keywords
    if rules.keywords:
        name_lower = recording.display_name.lower()
        results.append(any(kw.lower() in name_lower for kw in rules.keywords))
    
    # Check regex patterns
    if rules.patterns:
        import re
        results.append(any(re.search(p, recording.display_name) for p in rules.patterns))
    
    # Check source filter
    if rules.source_ids:
        results.append(recording.source_id in rules.source_ids)
    
    # Apply match_mode
    if rules.match_mode == "all":
        return all(results)
    else:  # "any"
        return any(results)
```

### Matching Strategy

**First-match strategy:**
- Templates sorted by `created_at ASC`
- First matching template wins
- Set `recording.template_id = template.id`
- Set `recording.is_mapped = True`

**Rationale:**
- KISS - простая и понятная логика
- Предсказуемость - всегда ясно какой template
- Performance - O(n) по templates
- Достаточно для 95% use cases

**Alternative (future):** Multiple template matching - см. [Architecture](#architecture--future)

### Auto-matching

**Когда происходит:**
1. **При sync** - новые recordings auto-matched
2. **При создании template** - existing unmapped recordings re-matched
3. **Manual re-match** - по запросу пользователя

**Example:**
```bash
# Sync triggers auto-matching
POST /recordings/sync

# Response
{
  "recordings_found": 10,
  "recordings_saved": 8,  # 2 были blank
  "matched": 6,           # 6 matched to templates
  "unmapped": 2           # 2 didn't match any template
}
```

---

## Re-match Functionality

### Что такое Re-match

**Re-match** - это пересопоставление recordings к templates после изменения matching rules или создания нового template.

### Use Cases

**1. Создали новый template:**
```
Before: 100 unmapped recordings
Create template "AI Lectures" with keywords: ["ML", "AI"]
→ Re-match automatically
After: 50 matched to "AI Lectures", 50 still unmapped
```

**2. Изменили matching rules:**
```
Template "Math Lectures" had keywords: ["Math"]
Update keywords to: ["Math", "Математика", "Алгебра"]
→ Re-match to apply new rules
```

**3. Recording был unmapped:**
```
Recording "Lecture ML" was unmapped
Create template matching "ML"
→ Re-match to assign template
```

### Re-match Modes

#### 1. Automatic Re-match (при создании template)

```python
@router.post("/templates", response_model=TemplateResponse)
async def create_template(
    data: TemplateCreate,
    ctx: ServiceContext = Depends(get_service_context)
):
    # Create template
    template = await template_service.create(data)
    
    # Auto re-match unmapped recordings
    matched_count = await template_matcher.rematch_unmapped_recordings(
        user_id=ctx.user_id,
        template=template
    )
    
    return template
```

**Поведение:**
- Находит recordings с `is_mapped=False`
- Проверяет matching rules нового template
- Если match → устанавливает `template_id`, `is_mapped=True`

---

#### 2. Manual Re-match (по запросу)

**Endpoint:** `POST /templates/{id}/rematch`

```bash
curl -X POST http://localhost:8000/api/v1/templates/5/rematch \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "template_id": 5,
  "template_name": "AI Lectures",
  "recordings_rematched": 25,
  "newly_matched": 15,
  "already_matched": 10
}
```

**Поведение:**
- Пересопоставляет ВСЕ recordings (включая already matched)
- Если recording matched к этому template → оставляет
- Если recording не matched → unmaps (если был mapped к этому template)
- Если recording matched к другому template → оставляет (не переназначает)

---

#### 3. Preview Re-match

**Endpoint:** `POST /templates/{id}/preview-rematch`

```bash
curl -X POST http://localhost:8000/api/v1/templates/5/preview-rematch \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "template_id": 5,
  "template_name": "AI Lectures",
  "would_match": [45, 67, 89, 102],
  "would_unmatch": [12, 34],
  "total_affected": 6
}
```

**Поведение:**
- Не изменяет БД (dry-run)
- Показывает какие recordings будут affected
- Полезно перед manual re-match

---

### Template Lifecycle & Auto-unmap

**При удалении template:**

```python
@router.delete("/templates/{template_id}")
async def delete_template(template_id: int, ctx: ServiceContext):
    # 1. Delete template
    await template_service.delete(template_id, ctx.user_id)
    
    # 2. Auto-unmap recordings
    await recording_service.unmap_by_template(template_id, ctx.user_id)
    
    # recordings.template_id = NULL
    # recordings.is_mapped = False
    # recordings.status сохраняется (UPLOADED остается UPLOADED)
```

**Симметричное поведение:**
- Create template → auto-rematch
- Delete template → auto-unmap

---

## Architecture & Future

### Current Architecture

**Single Template Mapping:**
```python
class Recording:
    template_id: int | None  # Single active template
    is_mapped: bool
```

**Pros:**
- ✅ Simple (KISS)
- ✅ Predictable (always one template)
- ✅ Fast (no complex queries)

**Cons:**
- ❌ Collision (если 2+ templates match)
- ❌ No alternatives (если template deleted)

---

### Future: Multiple Template Mapping

**Proposal (ADR):** Support multiple templates per recording

**Option 1: ARRAY in recordings**

```python
class Recording:
    template_id: int  # Active template
    mapped_template_ids: list[int]  # All matched (sorted by created_at)
```

**Pros:**
- Simple structure
- Fast access to alternatives

**Cons:**
- GIN index slower than B-tree
- No history/metadata
- Hard to revalidate

---

**Option 2: Separate Mapping Table** ← Recommended

```sql
CREATE TABLE recording_template_mappings (
    id SERIAL PRIMARY KEY,
    recording_id INT REFERENCES recordings(id),
    template_id INT REFERENCES recording_templates(id),
    
    is_active BOOLEAN DEFAULT TRUE,
    matched_at TIMESTAMP,
    unmapped_at TIMESTAMP,
    
    match_score FLOAT,  -- Future: confidence score
    matched_rules JSONB,  -- Which rules matched
    rank INT  -- Priority (1 = primary)
);
```

**Pros:**
- ✅ Full history (matched_at, unmapped_at)
- ✅ Metadata (match_score, matched_rules)
- ✅ Easy analytics (GROUP BY queries)
- ✅ Scalable (more rows)
- ✅ Safe concurrency (just INSERT)

**Cons:**
- Additional table
- Need JOINs for queries
- Migration required

**Decision:** Use separate table when needed (>10k recordings, >50 templates)

**См.:** [TEMPLATE_MAPPING_ARCHITECTURE.md](archive/TEMPLATE_MAPPING_ARCHITECTURE.md) - Detailed ADR

---

### Future Features

**1. Match Score:**
```python
mapping.match_score = calculate_match_score(recording, template)
# 1.0 = exact match
# 0.7 = keyword match
# 0.5 = pattern match
```

**2. Partial Matching:**
```python
# Recording partially matches template
mapping.matched_rules = ["keyword", "source_id"]  # but not "exact_match"
mapping.match_score = 0.6
```

**3. Template Priority:**
```python
template.priority = 10  # High priority
template.priority = 1   # Low priority

# Select by priority when multiple match
```

**4. Auto-revalidation:**
```python
# When template.matching_rules change
async def revalidate_template_mappings(template_id: int):
    mappings = await get_mappings(template_id, is_active=True)
    for mapping in mappings:
        if not template.matches(recording):
            mapping.is_active = False
            # Switch to next matching template
```

---

## API Reference

### Template CRUD

```
GET /templates - List templates
POST /templates - Create template
GET /templates/{id} - Get template
PATCH /templates/{id} - Update template
DELETE /templates/{id} - Delete template (auto-unmap recordings)
POST /templates/{id}/from-recording - Create from recording config
```

### Template Matching

```
POST /templates/{id}/preview-match - Preview which recordings would match
POST /templates/{id}/rematch - Re-match recordings to template
POST /templates/{id}/preview-rematch - Preview re-match (dry-run)
POST /templates/rematch-all - Re-match all templates
GET /templates/{id}/stats - Template statistics
```

### Recording Config Management

```
GET /recordings/{id}/config - Get resolved config (user → template → override)
PUT /recordings/{id}/config - Set override config
DELETE /recordings/{id}/config - Reset to template config
POST /recordings/{id}/config/save-as-template - Create template from config
```

### Filtering

```
GET /recordings?is_mapped=true - Get mapped recordings
GET /recordings?is_mapped=false - Get unmapped recordings
GET /recordings?template_id=5 - Get recordings for template
POST /bulk/process-mapped - Batch process mapped recordings
POST /bulk/process-unmapped - Batch process unmapped (custom config)
```

---

## Examples

### Example 1: Create Template for ML Lectures

```bash
POST /api/v1/templates
{
  "name": "ML Lectures",
  "matching_rules": {
    "keywords": ["ML", "Machine Learning", "Машинное обучение"],
    "patterns": ["Лекция \\d+:.*ML"],
    "source_ids": [1],  # Only from Zoom source 1
    "match_mode": "any"
  },
  "processing_config": {
    "transcription": {
      "enable_transcription": true,
      "language": "ru",
      "enable_topics": true,
      "granularity": "long"
    }
  },
  "metadata_config": {
    "title_template": "МО | {themes}",
    "youtube": {
      "playlist_id": "PLxxx",
      "privacy": "unlisted"
    }
  },
  "output_config": {
    "preset_ids": [1],
    "auto_upload": true
  }
}
```

**Result:** Template created, unmapped recordings auto-rematched

---

### Example 2: Preview Re-match

```bash
# Check which recordings would be affected
POST /api/v1/templates/5/preview-rematch

# Response
{
  "would_match": [45, 67, 89],
  "would_unmatch": [12],
  "total_affected": 4
}

# If looks good → apply
POST /api/v1/templates/5/rematch
```

---

### Example 3: Unmapped Recordings Workflow

```bash
# 1. Get unmapped recordings
GET /api/v1/recordings?is_mapped=false

# 2. Create template for them
POST /api/v1/templates {...}

# 3. They are auto-rematched now
GET /api/v1/recordings?template_id=NEW_ID

# 4. Batch process them
POST /api/v1/bulk/process
{
  "filters": {"template_id": NEW_ID}
}
```

---

## Best Practices

### 1. Template Naming

**Good:**
- "НИС: Современный ML" - specific, descriptive
- "Math Lectures: Calculus" - category + subcategory

**Bad:**
- "Template 1" - not descriptive
- "Test" - not production-ready

### 2. Matching Rules

**Tips:**
- Start with `keywords` (simple, reliable)
- Add `patterns` only if needed (complex)
- Use `exact_matches` for known titles
- Filter by `source_ids` if different sources have different rules

**Example progression:**
```
v1: keywords: ["ML"]
v2: keywords: ["ML", "Machine Learning"]
v3: keywords + patterns: ["ML.*Лекция"]
```

### 3. Testing Templates

```bash
# 1. Create with dry-run
POST /templates (with preview-match)

# 2. Check what matches
POST /templates/{id}/preview-match

# 3. If good → activate
PATCH /templates/{id} {"is_active": true}

# 4. Monitor stats
GET /templates/{id}/stats
```

### 4. Template Updates

**Безопасно:**
- Update `metadata_config` - применяется live
- Update `processing_config` - применяется live
- Add keywords - расширяет matching

**Требует re-match:**
- Remove keywords - сузит matching
- Change patterns - может unmatch recordings

---

---

## Metadata Configuration

### Output Preset Metadata

**Output Preset** содержит платформенные defaults (privacy, category, topics_display):

```json
{
  "name": "YouTube Unlisted",
  "platform": "youtube",
  "preset_metadata": {
    "privacy": "unlisted",
    "embeddable": true,
    "made_for_kids": false,
    "category_id": "27",
    "topics_display": {
      "format": "numbered_list",
      "max_count": 10
    }
  }
}
```

### Template Metadata Config

**Recording Template** содержит контент-специфичные настройки:

```json
{
  "name": "ML Lectures",
  "metadata_config": {
    "title_template": "МО | {themes}",
    "description_template": "Лекция по машинному обучению\n\n{topics}",
    "tags": ["ML", "AI", "Education"],
    "youtube": {
      "playlist_id": "PLxxx",
      "privacy": "unlisted"  // Override preset
    },
    "vk": {
      "group_id": -123456,
      "album_id": 63,
      "no_comments": false
    }
  }
}
```

### Template Variables

**Доступные переменные:**
- `{display_name}` - оригинальное название
- `{start_date}` - дата записи
- `{themes}` - извлеченные темы (comma-separated)
- `{topics}` - список topics (formatted)

**Topics Display Formats:**
- `numbered_list` - "1. Topic A\n2. Topic B"
- `bullet_list` - "• Topic A\n• Topic B"
- `comma_separated` - "Topic A, Topic B"
- `newline_separated` - "Topic A\nTopic B"

### Deep Merge Logic

**Template config overrides preset:**

```python
# Preset metadata
preset = {"privacy": "public", "category_id": 27}

# Template metadata_config
template = {"privacy": "unlisted", "playlist_id": "PLxxx"}

# Final (deep merge)
final = {"privacy": "unlisted", "category_id": 27, "playlist_id": "PLxxx"}
```

**Recording-level overrides:**
```python
# Recording.config_override can override both
recording_override = {"privacy": "private"}

# Final
final = {"privacy": "private", "category_id": 27, "playlist_id": "PLxxx"}
```

---

## См. также

- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - Bulk processing
- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - Architecture decisions
- [OAUTH.md](OAUTH.md) - OAuth credentials

---

**Документ обновлен:** Январь 2026  
**Статус:** Production Ready ✅
