# Руководство по Preset Metadata

## Обзор

Output Preset позволяет настроить параметры публикации видео на платформах YouTube и VK через поле `preset_metadata`.

⚠️ **VK Update (январь 2026):** VK больше не выдает расширенные API-доступы для новых приложений. Для multi-user функциональности используйте **Implicit Flow** (токен обновляется каждые 24 часа). См. [CREDENTIALS_GUIDE.md](CREDENTIALS_GUIDE.md) для деталей.

## 🔄 Разделение ответственности: Output Preset vs Template

**Новая архитектура (январь 2026):** Metadata разделяется между Output Preset (платформенные defaults) и Recording Template (контент-специфичные данные) для переиспользования.

### Output Preset (platform defaults)

**Назначение:** Общие, переиспользуемые настройки платформы

**Содержит:**
- Privacy settings (`privacy`, `embeddable`, `made_for_kids`)
- Platform defaults (`category_id`, `license`)
- Topics display format (`topics_display`)
- Embedding/commenting settings

**Пример:** "YouTube Unlisted Default"
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

### Recording Template (content-specific)

**Назначение:** Контент-специфичные настройки для курсов/серий/дисциплин

**Содержит (`metadata_config`):**
- Content metadata (`title_template`, `description_template`, `tags`)
- Media (`thumbnail_path`)
- Platform organization (`playlist_id` для YouTube, `group_id`/`album_id` для VK)
- Scheduling (`publish_at`)
- **Опционально:** Overrides для preset defaults

**Пример:** Template для курса "Временные ряды"
```json
{
  "name": "Временные ряды",
  "output_config": {
    "preset_ids": [1]
  },
  "metadata_config": {
    "title_template": "Временные ряды | {themes}",
    "description_template": "Лекция по курсу\n\n{topics}\n\nЗаписано: {record_time:DD.MM.YYYY}\nОпубликовано: {publish_time:date}",
    "playlist_id": "PLmA-1xX7IuzDK0OSCArxNjG_VDuYOXxTs",
    "thumbnail_path": "thumbnails/time_series.png",
    "tags": ["временные ряды", "статистика"],
    "topics_display": {
      "format": "bullet_list"
    }
  }
}
```

### Metadata Resolution (Deep Merge)

При загрузке видео metadata объединяется в следующем порядке:

```
1. Preset.preset_metadata (platform defaults)
2. Template.metadata_config (content-specific + overrides)  
3. Recording.processing_preferences.metadata_config (manual override)
```

**Пример итогового merge:**

```json
{
  "privacy": "unlisted",
  "embeddable": true,
  "category_id": "27",
  "topics_display": {
    "format": "bullet_list",
    "max_count": 10
  },
  "title_template": "Временные ряды | {topic}",
  "playlist_id": "PLmA-...",
  "tags": ["временные ряды"]
}
```

### Преимущества

- **DRY:** Один preset используется для множества templates
- **Гибкость:** Template может override любое поле из preset
- **Переиспользование:** Настройки платформы не дублируются
- **Масштабируемость:** Легко добавлять новые курсы/дисциплины

## Шаблоны (Template Rendering)

### Доступные переменные

**Основные:**
- `{display_name}` - название записи
- `{duration}` - длительность

**Время (с форматированием):**
- `{record_time}` - время записи (datetime)
- `{publish_time}` - время публикации (datetime)

**Темы:**
- `{themes}` - краткие темы для заголовка (первые 3 через запятую)
- `{topics}` - детальный форматированный список тем для описания (управляется `topics_display`)

### Форматирование времени

Время можно форматировать прямо в переменной:

```
{record_time:DD.MM.YYYY}       → 11.01.2026
{record_time:DD-MM-YY hh:mm}   → 11-01-26 14:30
{publish_time:date}            → 2026-01-11
{publish_time:time}            → 14:30
{record_time:YYYY-MM-DD}       → 2026-01-11
```

**Доступные токены:**
- `DD` - день (01-31)
- `MM` - месяц (01-12)
- `YY` - год 2-значный (26)
- `YYYY` - год 4-значный (2026)
- `hh` - час (00-23)
- `mm` - минута (00-59)
- `ss` - секунда (00-59)
- `date` - YYYY-MM-DD
- `time` - HH:MM
- `datetime` - YYYY-MM-DD HH:MM

### Синтаксис шаблонов

```
"{display_name} - {record_time:DD.MM.YYYY}"
"Публикация: {publish_time:date} в {publish_time:time}"
"Лекция: {themes}"
"{display_name}\n\nТемы:\n{topics}"
```

### Topics Display - гибкое форматирование тем

Для переменной `{topics}` можно настроить детальное форматирование через конфигурацию `topics_display`:

```json
{
  "topics_display": {
    "enabled": true,
    "max_count": 10,
    "min_length": 5,
    "max_length": 100,
    "format": "numbered_list",
    "separator": "\n",
    "prefix": "Темы:",
    "include_timestamps": false
  }
}
```

#### Параметры topics_display

| Параметр | Тип | Описание | По умолчанию |
|----------|-----|----------|--------------|
| `enabled` | boolean | Включить форматирование | `true` |
| `max_count` | int | Максимальное количество тем | `10` |
| `min_length` | int | Минимальная длина темы (фильтр) | `0` |
| `max_length` | int | Максимальная длина темы (фильтр) | `1000` |
| `format` | string | Формат списка | `"numbered_list"` |
| `separator` | string | Разделитель между темами | `"\n"` |
| `prefix` | string | Префикс перед списком | `""` |
| `include_timestamps` | boolean | Включать временные метки | `false` |

#### Форматы списка

- `numbered_list` - Нумерованный список (1. Тема 2. Тема)
- `bullet_list` - Маркированный список (• Тема)
- `dash_list` - Список с дефисом (- Тема)
- `comma_separated` - Через запятую (Тема1, Тема2, Тема3)
- `inline` - Через разделитель | (Тема1 | Тема2 | Тема3)

#### Примеры topics_display

**Нумерованный список:**
```json
{
  "topics_display": {
    "format": "numbered_list",
    "max_count": 10,
    "prefix": "Темы лекции:",
    "separator": "\n"
  }
}
```
Результат:
```
Темы лекции:
1. Генеративные модели
2. Variational Autoencoders
3. GANs
```

**Маркированный список:**
```json
{
  "topics_display": {
    "format": "bullet_list",
    "max_count": 5,
    "min_length": 10,
    "separator": "\n"
  }
}
```
Результат:
```
• Генеративные модели
• Variational Autoencoders
• GANs
```

**Inline через запятую:**
```json
{
  "topics_display": {
    "format": "comma_separated",
    "max_count": 3
  }
}
```
Результат:
```
Генеративные модели, VAE, GANs
```

---

## YouTube Preset Metadata

### Полная структура

```json
{
  "title_template": "{display_name} | {themes}",
  "description_template": "Лекция\n\n{topics}\n\nЗаписано: {record_time:DD.MM.YYYY}\nОпубликовано: {publish_time:date}",
  "tags": ["образование", "лекция", "ml"],
  "category_id": 27,
  "privacy": "unlisted",
  "playlist_id": "PLxxx...",
  "publish_at": "2026-01-10T15:00:00Z",
  "thumbnail_path": "/path/to/thumbnail.jpg",
  "made_for_kids": false,
  "embeddable": true,
  "license": "youtube",
  "public_stats_viewable": true
}
```

### Параметры YouTube

| Параметр | Тип | Описание | Пример |
|----------|-----|----------|--------|
| `title_template` | string | Шаблон заголовка | `"{display_name} | {themes}"` |
| `description_template` | string | Шаблон описания | `"{summary}"` |
| `tags` | array | Теги видео (макс 500) | `["education", "ml"]` |
| `category_id` | int/string | ID категории YouTube | `27` (Education) |
| `privacy` | string | Приватность | `"private"`, `"unlisted"`, `"public"` |
| `playlist_id` | string | ID плейлиста | `"PLxxx..."` |
| `publish_at` | string | Время публикации (ISO 8601) | `"2026-01-10T15:00:00Z"` |
| `thumbnail_path` | string | Путь к миниатюре | `"/data/thumbnails/thumb.jpg"` |
| `made_for_kids` | boolean | Контент для детей | `false` |
| `embeddable` | boolean | Разрешить встраивание | `true` |
| `license` | string | Лицензия | `"youtube"` или `"creativeCommon"` |
| `public_stats_viewable` | boolean | Публичная статистика | `true` |

### YouTube Categories

- `1` - Film & Animation
- `2` - Autos & Vehicles
- `10` - Music
- `15` - Pets & Animals
- `17` - Sports
- `19` - Travel & Events
- `20` - Gaming
- `22` - People & Blogs
- `23` - Comedy
- `24` - Entertainment
- `25` - News & Politics
- `26` - Howto & Style
- `27` - Education
- `28` - Science & Technology

### Отложенная публикация (publishAt)

**Важно:**
- Формат: ISO 8601 с timezone (`Z` или `+00:00`)
- При использовании `publish_at` privacy автоматически устанавливается в `private`
- Время публикации должно быть в будущем

```json
{
  "publish_at": "2026-01-15T18:00:00Z"
}
```

### Примеры YouTube presets

#### Пример 1: Публичная лекция с форматированными темами

```json
{
  "title_template": "(Л) {display_name}",
  "description_template": "Лекция по курсу\n\n{topics}\n\nЗаписано: {record_time:DD.MM.YYYY}\nОпубликовано: {publish_time:date}",
  "topics_display": {
    "enabled": true,
    "format": "numbered_list",
    "max_count": 10,
    "min_length": 5,
    "prefix": "Темы лекции:",
    "separator": "\n"
  },
  "tags": ["лекция", "образование", "наука"],
  "category_id": 27,
  "privacy": "public",
  "playlist_id": "PLxxxLectures",
  "thumbnail_path": "/data/thumbnails/lecture.jpg",
  "made_for_kids": false,
  "embeddable": true
}
```

#### Пример 2: Скрытая запись с отложенной публикацией

```json
{
  "title_template": "{display_name} - {start_time}",
  "description_template": "{summary}",
  "tags": ["вебинар"],
  "category_id": 27,
  "publish_at": "2026-01-20T12:00:00Z",
  "privacy": "private"
}
```

---

## VK Preset Metadata

### Полная структура

```json
{
  "title_template": "{display_name}",
  "description_template": "Видео\n\nТемы:\n{topics}\n\nОпубликовано: {publish_time:DD.MM.YYYY}",
  "group_id": 123456,
  "album_id": 67890,
  "privacy_view": 0,
  "privacy_comment": 0,
  "no_comments": false,
  "repeat": false,
  "wallpost": true,
  "thumbnail_path": "/path/to/thumbnail.jpg"
}
```

### Параметры VK

| Параметр | Тип | Описание | Пример |
|----------|-----|----------|--------|
| `title_template` | string | Шаблон заголовка | `"{display_name}"` |
| `description_template` | string | Шаблон описания | `"{summary}"` |
| `group_id` | int | ID группы для публикации | `123456` |
| `album_id` | int | ID альбома | `67890` |
| `privacy_view` | int | Приватность просмотра | `0-3` (см. ниже) |
| `privacy_comment` | int | Приватность комментариев | `0-3` |
| `no_comments` | boolean | Отключить комментарии | `false` |
| `repeat` | boolean | Зациклить видео | `false` |
| `wallpost` | boolean | Опубликовать на стене | `true` |
| `thumbnail_path` | string | Путь к миниатюре | `"/data/thumbnails/thumb.jpg"` |

### VK Privacy Settings

- `0` - Все пользователи
- `1` - Только друзья
- `2` - Друзья и друзья друзей
- `3` - Только я

### Примеры VK presets

#### Пример 1: Публикация в группу с постом на стене

```json
{
  "title_template": "{display_name}",
  "description_template": "Новая лекция!\n\nТемы:\n{topics}\n\nОпубликовано: {publish_time:date}",
  "group_id": 123456,
  "privacy_view": 0,
  "privacy_comment": 0,
  "no_comments": false,
  "repeat": false,
  "wallpost": true
}
```

#### Пример 2: Приватная запись в альбом

```json
{
  "title_template": "{display_name} - {start_time}",
  "description_template": "{summary}",
  "group_id": 123456,
  "album_id": 67890,
  "privacy_view": 3,
  "privacy_comment": 3,
  "no_comments": true,
  "wallpost": false
}
```

---

## API Endpoints

### Создание preset с metadata

```bash
POST /api/v1/output-presets/
```

```json
{
  "name": "YouTube Лекции",
  "description": "Пресет для публикации лекций на YouTube",
  "platform": "youtube",
  "credential_id": 1,
  "preset_metadata": {
    "title_template": "(Л) {display_name}",
    "description_template": "{summary}",
    "tags": ["лекция", "образование"],
    "category_id": 27,
    "privacy": "unlisted",
    "playlist_id": "PLxxx..."
  }
}
```

### Обновление preset metadata

```bash
PATCH /api/v1/output-presets/{preset_id}
```

```json
{
  "preset_metadata": {
    "publish_at": "2026-01-20T15:00:00Z",
    "privacy": "private"
  }
}
```

---

## Валидация

### YouTube

- `privacy`: должен быть `private`, `public` или `unlisted`
- `category_id`: должен быть положительным числом
- `tags`: максимум 500 тегов
- `publish_at`: должен быть в формате ISO 8601 с timezone
- При использовании `publish_at` privacy автоматически устанавливается в `private`

### VK

- `group_id`: должен быть положительным числом
- `album_id`: должен быть положительным числом
- `privacy_view`: должен быть 0-3
- `privacy_comment`: должен быть 0-3

---

## Миграция с Legacy Config

### До (config)

```python
# config/youtube.json
{
  "default_privacy": "unlisted",
  "default_language": "ru"
}
```

### После (preset_metadata)

```json
{
  "privacy": "unlisted",
  "tags": ["ru"],
  "category_id": 27
}
```

---

## Best Practices

1. **Используйте шаблоны** для динамического title/description
2. **Настройте privacy** в зависимости от типа контента
3. **Добавьте tags** для лучшей находимости
4. **Используйте playlists** для организации контента
5. **Настройте thumbnail** для привлечения внимания
6. **Используйте publish_at** для запланированных публикаций

---

## Troubleshooting

### YouTube: "Privacy must be private for scheduled videos"

При использовании `publish_at` privacy автоматически устанавливается в `private`. Это требование YouTube API.

### VK: "Group not found"

Убедитесь, что `group_id` корректен и у вас есть права на публикацию в группе.

### Thumbnail не устанавливается

Проверьте:
- Файл существует по указанному пути
- Формат файла (JPEG/PNG)
- Размер файла (< 2MB для YouTube, < 5MB для VK)

### Пустой title/description

Если шаблон не может быть отрендерен (например, переменная отсутствует), используется fallback:
- title: `display_name` или `"Recording"`
- description: `"Uploaded on {start_time}"`

---

## Changelog

### v2.9 (2026-01-08)

- ✅ Добавлен template rendering для title/description
- ✅ Добавлена поддержка `publish_at` для YouTube
- ✅ Добавлены все параметры YouTube (tags, category, playlist, thumbnail)
- ✅ Добавлены все параметры VK (group, album, privacy, wallpost)
- ✅ Pydantic валидация preset_metadata
- ✅ Автоматический fallback для пустых шаблонов

