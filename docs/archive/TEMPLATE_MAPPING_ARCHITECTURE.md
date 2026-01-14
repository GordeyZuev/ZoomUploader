# Template Mapping Architecture - ADR

**Status:** 📋 Proposal  
**Date:** 14.01.2026  
**Context:** Multiple templates могут match один recording - нужна архитектура для handling коллизий

---

## 🎯 Проблема

**Текущая архитектура:**
```python
class RecordingModel:
    template_id: int | None  # Один активный template
    is_mapped: bool
```

**Проблемы:**
1. **Collision:** Если 2+ templates матчат один recording - выбирается только один (first by created_at)
2. **Удаление template:** При удалении template recording unmapped, хотя может быть другой подходящий template
3. **Нет истории:** Невозможно узнать какие templates matched в прошлом
4. **Revalidation сложен:** При изменении matching_rules нет механизма проверки

---

## 🏗️ Вариант 1: ARRAY в recordings

### Структура
```python
class RecordingModel(Base):
    template_id: int | None  # Активный template
    mapped_template_ids: list[int] | None = mapped_column(
        ARRAY(Integer),
        comment="Все templates которые матчат (sorted by created_at DESC)"
    )
    is_mapped: bool
```

### Логика
```python
# При matching
recording.mapped_template_ids = [10, 8, 5]  # Sorted by created_at DESC
recording.template_id = 10  # Самый новый = активный

# При удалении template 10
recording.mapped_template_ids.remove(10)  # → [8, 5]
recording.template_id = 8  # Автоматический switch на следующий
```

### Плюсы ✅
- Простая структура (один массив)
- Не требует дополнительных таблиц
- Быстрый доступ к alternatives
- Легко понять логику

### Минусы ❌
- **Performance:** GIN индекс медленнее B-tree на UPDATE
- **Масштабируемость:** Если 100+ templates матчат → большой массив
- **Нет timestamp:** Когда template был matched?
- **Нет metadata:** Score matching, конфигурация на момент matching
- **Revalidation сложен:** Нужно пересчитывать весь массив при изменении rules
- **Конкурентность:** Race conditions при одновременном UPDATE массива
- **Аналитика:** Сложные запросы с `unnest()`

### Queries
```sql
-- Найти recordings с template 10
SELECT * FROM recordings 
WHERE mapped_template_ids @> ARRAY[10];
-- Performance: ~50-100ms на 100k (GIN index)

-- Аналитика: сколько recordings на template
SELECT template_id, COUNT(*) 
FROM recordings, unnest(mapped_template_ids) AS template_id
GROUP BY template_id;
-- Сложный запрос
```

---

## 🏗️ Вариант 2: Отдельная таблица Mapping

### Структура
```python
class RecordingTemplateMapping(Base):
    """M2M таблица: Recording ↔ Template."""
    __tablename__ = "recording_template_mappings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE")
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("recording_templates.id", ondelete="CASCADE")
    )
    
    # Metadata
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    matched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unmapped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Для будущих фич
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_rules: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    
    # Для ordering (1 = primary, 2 = secondary)
    rank: Mapped[int] = mapped_column(Integer, default=1)

# Recording остается простым
class RecordingModel(Base):
    template_id: int | None  # Активный (для удобства, можно убрать)
    is_mapped: bool
    
    # Relationship
    template_mappings: Mapped[list[RecordingTemplateMapping]] = relationship(...)
```

### Логика
```python
# При matching
mapping = RecordingTemplateMapping(
    recording_id=61,
    template_id=10,
    is_active=True,
    matched_at=datetime.utcnow(),
    rank=1,  # Primary
    match_score=0.95
)

# При удалении template 10
# 1. Помечаем mapping как inactive
UPDATE recording_template_mappings
SET is_active = False, unmapped_at = NOW()
WHERE template_id = 10 AND recording_id = 61;

# 2. Активируем следующий по rank
UPDATE recording_template_mappings
SET is_active = True, rank = 1
WHERE recording_id = 61 AND template_id = 8;

# 3. Обновляем recording
UPDATE recordings SET template_id = 8 WHERE id = 61;
```

### Плюсы ✅
- **Performance:** B-tree индекс быстрее (~10-20ms на 100k)
- **История:** Полная история с timestamps
- **Metadata:** Score, matched_rules, config_snapshot
- **Аналитика:** Простые GROUP BY запросы
- **Масштабируемость:** Отлично масштабируется (больше строк)
- **Конкурентность:** Безопасно (просто INSERT строк)
- **Revalidation:** Легко помечать invalid mappings
- **Debugging:** Видно полную историю changes
- **Будущие фичи:** Гибкая структура (priority, confidence, partial matching)

### Минусы ❌
- Дополнительная таблица
- Сложнее queries (нужны JOIN)
- Нужна миграция
- Больше кода для поддержки

### Queries
```sql
-- Найти recordings с template 10
SELECT r.* FROM recordings r
JOIN recording_template_mappings m ON r.id = m.recording_id
WHERE m.template_id = 10 AND m.is_active = True;
-- Performance: ~10-20ms на 100k (B-tree index)

-- Аналитика: сколько recordings на template
SELECT template_id, COUNT(*) 
FROM recording_template_mappings
WHERE is_active = True
GROUP BY template_id;
-- Простой запрос

-- История для recording
SELECT template_id, matched_at, unmapped_at, match_score
FROM recording_template_mappings
WHERE recording_id = 61
ORDER BY matched_at DESC;
-- Полная история
```

---

## 🏗️ Вариант 3: Hybrid (компромисс)

### Структура
```python
class RecordingModel(Base):
    # Для удобства - активный template без JOIN
    template_id: int | None
    is_mapped: bool

class RecordingTemplateMapping(Base):
    # Только для alternatives и истории
    recording_id: int
    template_id: int
    is_active: bool
    matched_at: datetime
    rank: int
```

### Плюсы ✅
- `recording.template_id` для быстрого доступа (без JOIN)
- `mappings` таблица для истории и alternatives
- Постепенная миграция (сначала только active, потом alternatives)

### Минусы ❌
- Дублирование данных (template_id в двух местах)
- Риск рассинхронизации
- Нужна логика синхронизации

---

## 📊 Сравнение

| Критерий | ARRAY | TABLE | Hybrid | Победитель |
|----------|-------|-------|--------|-----------|
| Простота структуры | ✅ | ❌ | ⚠️ | ARRAY |
| SELECT performance | ⚠️ 50-100ms | ✅ 10-20ms | ✅ | TABLE |
| UPDATE performance | ❌ Медленно | ✅ Быстро | ✅ | TABLE |
| Масштабируемость | ⚠️ Ограничена | ✅ Отлично | ✅ | TABLE |
| История | ❌ | ✅✅ | ✅ | TABLE |
| Аналитика | ❌ Сложно | ✅ Просто | ✅ | TABLE |
| Debugging | ❌ | ✅✅ | ✅ | TABLE |
| Конкурентность | ❌ Race | ✅ Безопасно | ✅ | TABLE |
| Будущие фичи | ❌ Негибко | ✅✅ Гибко | ✅ | TABLE |
| Миграция | ❌ Сложно | ⚠️ Средне | ✅ Постепенно | Hybrid |
| Код | ✅ Простой | ❌ Сложнее | ⚠️ | ARRAY |

**Итого: TABLE - 7, ARRAY - 2, Hybrid - 8**

---

## 🎯 Рекомендация

### Для текущего масштаба (<10k recordings, <50 templates):
→ **ARRAY подход** - достаточно для MVP

### Для роста (>10k recordings, >50 templates):
→ **TABLE подход** - enterprise-ready

### Оптимальный путь:
→ **Hybrid с постепенной миграцией:**

**Phase 1 (MVP):** Текущая архитектура (только `template_id`)
**Phase 2 (Growth):** Добавить таблицу `mappings` для alternatives
**Phase 3 (Scale):** Полная миграция на `mappings` с историей

---

## 🚀 Будущие фичи (с TABLE)

### 1. Match Score
```python
# Ranking templates по качеству matching
mapping.match_score = calculate_match_score(recording, template)
# 1.0 = exact_match, 0.5 = keyword match, 0.3 = pattern match
```

### 2. Partial Matching
```python
# Recording частично матчит template
mapping.matched_rules = ["keyword", "source_id"]  # Но не "exact_match"
mapping.match_score = 0.7  # Частичный match
```

### 3. Template Priority
```python
# User задает priority для templates
template.priority = 10  # High priority
template.priority = 1   # Low priority

# При matching выбирается highest priority
SELECT * FROM recording_template_mappings
WHERE recording_id = 61
ORDER BY templates.priority DESC, matched_at DESC
LIMIT 1;
```

### 4. Config Snapshot
```python
# Сохраняем конфигурацию на момент matching
mapping.config_snapshot = {
    "processing_config": template.processing_config,
    "metadata_config": template.metadata_config,
    "output_config": template.output_config
}
# Даже если template удален - конфиг сохранен
```

### 5. Auto-revalidation
```python
# При изменении template.matching_rules
async def revalidate_template_mappings(template_id: int):
    mappings = await get_mappings(template_id, is_active=True)
    for mapping in mappings:
        recording = await get_recording(mapping.recording_id)
        if not template.matches(recording):
            mapping.is_active = False
            mapping.unmapped_at = datetime.utcnow()
            # Switch к следующему matching template
```

---

## 📝 Migration Plan (если выбрали TABLE)

### Step 1: Создать таблицу
```sql
CREATE TABLE recording_template_mappings (
    id SERIAL PRIMARY KEY,
    recording_id INTEGER REFERENCES recordings(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES recording_templates(id) ON DELETE CASCADE,
    is_active BOOLEAN DEFAULT TRUE,
    matched_at TIMESTAMP DEFAULT NOW(),
    unmapped_at TIMESTAMP,
    rank INTEGER DEFAULT 1,
    match_score FLOAT,
    matched_rules JSONB,
    config_snapshot JSONB
);

CREATE INDEX idx_mappings_recording ON recording_template_mappings(recording_id);
CREATE INDEX idx_mappings_template ON recording_template_mappings(template_id);
CREATE INDEX idx_mappings_active ON recording_template_mappings(recording_id, is_active);
```

### Step 2: Миграция данных
```python
# Мигрировать существующие mappings
INSERT INTO recording_template_mappings (recording_id, template_id, is_active, rank)
SELECT id, template_id, TRUE, 1
FROM recordings
WHERE template_id IS NOT NULL;
```

### Step 3: Обновить код
- Добавить `RecordingTemplateMapping` model
- Обновить matching logic
- Обновить delete template logic
- Добавить API endpoints для alternatives

### Step 4: Backfill alternatives (опционально)
```python
# Найти все подходящие templates для каждой записи
# Медленно, но можно делать background task
```

---

## 🤔 Вопросы для решения

1. **Масштаб:** Сколько recordings/templates ожидается?
2. **Частота операций:** Что чаще - matching или чтение?
3. **Критичность истории:** Нужна ли полная история?
4. **Tolerance к сложности:** Готовы поддерживать доп. таблицу?
5. **Миграция:** Zero-downtime требуется?

---

**Решение:** TBD  
**Responsible:** Team  
**Next steps:** Обсудить масштаб и приоритеты
