# Platform-Specific Metadata в Templates

## Проблема

При использовании одного Template для загрузки на несколько платформ (YouTube и VK), возникала проблема:

- **Preset YouTube** имел: `description_template: "Uploaded on {record_time:date}..."`
- **Preset VK** имел: `description_template: "Запись пары..."`
- **Template** имел один общий `description_template` (НЕ разделенный по платформам)

При deep merge (Preset → Template):
- Template перезаписывал top-level `description_template`
- **Оба YouTube и VK получали одинаковый шаблон из Template!**

## Решение

Реализована поддержка **platform-specific metadata** в Template с обратной совместимостью.

### Новая структура Template.metadata_config

```json
{
  "youtube": {
    "description_template": "YouTube specific template...",
    "title_template": "...",
    "playlist_id": "..."
  },
  "vk": {
    "description_template": "VK specific template...",
    "title_template": "...",
    "album_id": "..."
  },
  "common": {
    "tags": ["общие", "теги"],
    "topics_display": {...}
  },
  "title_template": "Fallback for old templates"
}
```

### Логика Merge (приоритет снизу вверх)

1. **Preset.preset_metadata** (platform defaults)
2. **Template.metadata_config.common** (если есть)
3. **Template.metadata_config[platform]** (platform-specific, если есть)
4. **Template.metadata_config (top-level)** (backward compatibility, пропуская ключи `youtube`, `vk`, `common`)
5. **Recording.processing_preferences.metadata_config** (manual override)

### Примеры

#### Пример 1: Platform-specific templates

```json
{
  "name": "Курс ML",
  "metadata_config": {
    "youtube": {
      "description_template": "YouTube: {topics}\n\nUpload: {publish_time:date}",
      "playlist_id": "PLxxx..."
    },
    "vk": {
      "description_template": "VK: 🔹 {topics}\n\nДата: {publish_time:DD.MM.YYYY}",
      "album_id": "67"
    },
    "common": {
      "title_template": "ML Course | {themes}",
      "topics_display": {
        "format": "numbered_list",
        "max_count": 20
      }
    }
  }
}
```

**Результат для YouTube:**
- `title_template`: "ML Course | {themes}" (из common)
- `description_template`: "YouTube: {topics}..." (из youtube)
- `playlist_id`: "PLxxx..." (из youtube)
- `topics_display`: {...} (из common)

**Результат для VK:**
- `title_template`: "ML Course | {themes}" (из common)
- `description_template`: "VK: 🔹 {topics}..." (из vk)
- `album_id`: "67" (из vk)
- `topics_display`: {...} (из common)

#### Пример 2: Backward compatibility (старый формат)

```json
{
  "name": "Старый Template",
  "metadata_config": {
    "title_template": "Old Style | {themes}",
    "description_template": "Common for all platforms",
    "topics_display": {...}
  }
}
```

**Результат:**
- Оба YouTube и VK получат одинаковые `title_template` и `description_template`
- Работает как раньше (обратная совместимость)

#### Пример 3: Смешанный формат

```json
{
  "name": "Mixed Template",
  "metadata_config": {
    "youtube": {
      "playlist_id": "PLxxx..."
    },
    "vk": {
      "album_id": "67"
    },
    "title_template": "Common title | {themes}",
    "description_template": "Common description",
    "topics_display": {...}
  }
}
```

**Результат:**
- YouTube: получит `playlist_id` из `youtube`, остальное из top-level
- VK: получит `album_id` из `vk`, остальное из top-level

### Исправление проблемы с мутацией

Также исправлена проблема с **мутацией shared state** в `_merge_configs`:

**Было:**
```python
result = base.copy()  # Shallow copy - мутирует оригинал!
```

**Стало:**
```python
import copy
result = copy.deepcopy(base)  # Deep copy - безопасно
```

Это предотвращает ситуацию, когда второй вызов `resolve_upload_metadata` (для VK) мутирует результат первого вызова (для YouTube).

## Миграция существующих Templates

### Если Template НЕ использует platform-specific поля

**Ничего делать не нужно!** Старый формат продолжит работать.

### Если Template нужно разделить по платформам

1. Создайте ключи `youtube` и `vk` в `metadata_config`
2. Переместите platform-specific поля внутрь соответствующих ключей
3. Общие поля можно оставить в top-level или переместить в `common`

**Пример миграции:**

**Было:**
```json
{
  "metadata_config": {
    "title_template": "Course | {themes}",
    "description_template": "Topics: {topics}",
    "playlist_id": "PLxxx...",
    "album_id": "67"
  }
}
```

**Стало:**
```json
{
  "metadata_config": {
    "youtube": {
      "description_template": "YouTube style: {topics}",
      "playlist_id": "PLxxx..."
    },
    "vk": {
      "description_template": "VK style: 🔹 {topics}",
      "album_id": "67"
    },
    "common": {
      "title_template": "Course | {themes}"
    }
  }
}
```

## API Changes

Никаких breaking changes в API! Все изменения обратно совместимы.

## Testing

Для тестирования:

1. Создайте Template с platform-specific metadata
2. Привяжите к нему recording
3. Запустите загрузку на обе платформы
4. Проверьте логи `[Metadata Resolution]` чтобы увидеть процесс merge

Логи покажут:
```
[Metadata Resolution] Base preset 'YouTube Unlisted' (platform=youtube) metadata keys: [...]
[Metadata Resolution] Preset has description_template: Uploaded on ...
[Metadata Resolution] Merging template 'Course' metadata_config keys: ['youtube', 'vk', 'common']
[Metadata Resolution] Merging template 'common' metadata
[Metadata Resolution] Merging template 'youtube' specific metadata
[Metadata Resolution] Merging template top-level fields: []
[Metadata Resolution] Final description_template: YouTube style: ...
```

## См. также

- [PRESET_METADATA_GUIDE.md](PRESET_METADATA_GUIDE.md) - Полное руководство по Preset Metadata
- [TEMPLATE_REMATCH_FEATURE.md](TEMPLATE_REMATCH_FEATURE.md) - Автоматическое matching Templates

