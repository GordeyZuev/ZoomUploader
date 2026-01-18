# 🔍 Media System Audit & Redesign

**Дата:** 2026-01-16  
**Статус:** Critical Issues Found  
**Приоритет:** 🔴 Высокий

---

## 📊 Текущее состояние

### Структура директорий (фактическая)

```
media/
├── data.db                          # ❌ ПРОБЛЕМА: DB файл в media
├── video/                           # ❌ LEGACY: не используется
│   ├── temp_processing/
│   └── unprocessed/
├── transcriptions/                  # ❌ LEGACY: не используется
├── templates/
│   └── thumbnails/                  # ✅ OK: 22 глобальных thumbnails
│       ├── applied_python.png
│       ├── machine_learning.png
│       └── ...
└── user_{id}/
    ├── video/
    │   ├── unprocessed/             # ✅ OK
    │   ├── processed/               # ✅ OK
    │   └── temp_processing/         # ⚠️ Не очищается
    ├── audio/
    │   └── processed/               # ❌ ПРОБЛЕМА: дублирование
    ├── processed_audio/             # ❌ ПРОБЛЕМА: дублирование
    ├── transcriptions/
    │   ├── {recording_id}/          # ✅ OK
    │   │   ├── master.json
    │   │   └── topics_v1.json
    └── thumbnails/                  # ❌ ПРОБЛЕМА: дублируются templates
        ├── applied_python.png       # Копия из templates/
        └── ...
```

---

## 🚨 Критические проблемы

### 1. Дублирование audio директорий

**Проблема:**
```python
# UserPathManager.get_audio_dir() возвращает:
return self.get_user_root(user_id) / "processed_audio"

# Но фактически существуют ОБА:
user_4/audio/processed/
user_4/processed_audio/

# Файлы разбросаны:
$ find media/user_4 -name "*.mp3"
media/user_4/audio/processed/test_nikita_26-01-05_17-00_processed.mp3
media/user_4/audio/processed/Тюлягин_GenDL_25-12-25_12-55_processed.mp3
```

**Причина:** Legacy код + incomplete refactoring

**Решение:**
- Стандартизировать на `user_{id}/audio/`
- Migration script для переноса файлов
- Обновить `UserPathManager.get_audio_dir()`

**Impact:** Medium (inconsistency, но не ломает функциональность)

---

### 2. Thumbnails дублируются для каждого пользователя

**Проблема:**
```python
# ThumbnailManager.initialize_user_thumbnails()
if copy_templates:
    for template_file in self.templates_dir.glob("*.png"):
        shutil.copy2(template_file, target_file)  # ❌ Копирует ВСЕ

# Результат:
# 22 thumbnails * N users = огромный waste
# media/templates/thumbnails/: 22 файла (~5 MB)
# media/user_4/thumbnails/: 22 файла (~5 MB)
# media/user_5/thumbnails/: 22 файла (~5 MB)
# media/user_6/thumbnails/: 22 файла (~5 MB)
# Итого: 5 MB * 4 = 20 MB (для 4 пользователей)
```

**Решение:**
- Не копировать templates по умолчанию
- Использовать fallback: `user_thumbs → templates`
- Копировать только при изменении пользователем

**Impact:** High (storage waste, особенно при масштабировании)

---

### 3. Orphaned files при delete recording

**Проблема:**
```python
# api/repositories/recording_repos.py:564
async def delete(self, recording: RecordingModel) -> None:
    await self.session.delete(recording)  # ← Только БД!
    await self.session.flush()
    # ❌ Файлы остаются на диске!

# Что остается:
# - local_video_path: ~/video/unprocessed/142_original.mp4
# - processed_video_path: ~/video/processed/142_trimmed.mp4
# - processed_audio_path: ~/audio/142_processed.mp3
# - transcription_dir: ~/transcriptions/142/
```

**Последствия:**
- Storage leak (quota не освобождается)
- Orphaned files накапливаются
- Пользователь платит за удаленные recordings

**Решение:**
```python
async def delete(self, recording: RecordingModel) -> None:
    # 1. Delete files FIRST
    file_manager = FileManager()
    await file_manager.delete_recording_files(recording)
    
    # 2. Update quota
    # 3. Delete DB record
    await self.session.delete(recording)
```

**Impact:** 🔴 Critical (финансовые потери для пользователей)

---

### 4. Имена файлов по display_name

**Проблема:**
```bash
# Реальные файлы:
media/user_4/video/processed/Тюлягин_GenDL_25-12-25_12-55_processed.mp4
media/user_4/audio/processed/Перевод_на_ИИ_25-12-26_07-21_processed.mp3

# Проблемы:
1. Кириллица (encoding issues на некоторых FS)
2. Длинные имена (>50 chars)
3. Коллизии при одинаковых display_name + time
4. Сложно найти файл по recording_id
5. Спецсимволы даже после sanitize
```

**Решение:**
```python
# ID-based naming
media/user_4/video/processed/142_trimmed.mp4
media/user_4/audio/142_processed.mp3
media/user_4/transcriptions/142/master.json

# Преимущества:
✅ Уникальность гарантирована
✅ Короткие пути
✅ Быстрый поиск по ID
✅ Нет проблем с encoding
```

**Impact:** High (UX + reliability)

---

### 5. Legacy директории

**Проблема:**
```bash
media/video/           # ❌ Не используется
media/transcriptions/  # ❌ Не используется
media/data.db          # ❌ DB файл в media директории
```

**Решение:**
- Удалить пустые legacy директории
- Переместить `data.db` в root (если используется)

**Impact:** Low (cleanup, но не критично)

---

### 6. Нет централизованной очистки

**Проблема:**
```python
# Нет функций для:
1. Cleanup orphaned files (файлы без записей в БД)
2. Cleanup temp files (temp_processing/ накапливаются)
3. Cleanup expired recordings (expire_at прошло)
4. Vacuum старых transcriptions
```

**Последствия:**
- Диск заполняется мусором
- Quota показывает неверные данные
- Performance degradation (много файлов)

**Решение:**
```python
# Celery periodic tasks
@celery_app.task
def cleanup_temp_files_task():
    """Hourly: delete files older than 24h"""

@celery_app.task
def cleanup_expired_recordings_task():
    """Daily: delete recordings past expire_at"""

@celery_app.task
def cleanup_orphaned_files_task():
    """Weekly: find files without DB records"""
```

**Impact:** 🔴 Critical (operational stability)

---

### 7. Quota tracking не автоматический

**Проблема:**
```python
# utils/user_paths.py:104
def get_user_storage_size(self, user_id: int) -> int:
    # Считает размер, НО:
    # 1. Нужно вызывать вручную
    # 2. Не обновляет quota_usage автоматически
    # 3. Медленно (os.walk по всей директории)
    total_size = 0
    for dirpath, _dirnames, filenames in os.walk(user_root):
        for filename in filenames:
            total_size += file_path.stat().st_size
    return total_size
```

**Решение:**
```python
class FileManager:
    async def save_file(self, path, content, user_id):
        # 1. Save file
        file_size = len(content)
        
        # 2. Update quota AUTOMATICALLY
        await QuotaService.track_storage_added(user_id, file_size)
    
    async def delete_file(self, path, user_id):
        # 1. Get file size
        file_size = path.stat().st_size
        
        # 2. Delete file
        path.unlink()
        
        # 3. Update quota AUTOMATICALLY
        await QuotaService.track_storage_removed(user_id, file_size)
```

**Impact:** High (quota accuracy, billing)

---

### 8. temp_processing не очищается

**Проблема:**
```python
# UserPathManager.get_temp_processing_dir()
return self.get_video_dir(user_id) / "temp_processing"

# Используется в video_processor.py для FFmpeg
# ❌ Никогда не очищается!
# Результат: Накопление временных файлов
```

**Пример:**
```bash
$ du -sh media/user_4/video/temp_processing/
2.5G    media/user_4/video/temp_processing/
# Файлы от неудачных обработок, старые temp файлы
```

**Решение:**
- Celery task для cleanup (hourly)
- Удалять файлы старше 24 часов
- Context manager для auto-cleanup:
  ```python
  async with temp_file_context(user_id, recording_id) as temp_path:
      # Process file
      pass
  # Auto-cleanup on exit
  ```

**Impact:** High (storage waste)

---

### 9. Paths как strings в БД

**Проблема:**
```python
# database/models.py
local_video_path: Mapped[str | None] = mapped_column(String(1000))
processed_video_path: Mapped[str | None] = mapped_column(String(1000))
processed_audio_path: Mapped[str | None] = mapped_column(String(1000))
transcription_dir: Mapped[str | None] = mapped_column(String(1000))

# Проблемы:
1. Относительные vs абсолютные (inconsistency)
2. При смене storage (S3) - нужно обновлять ВСЕ пути
3. Нет валидации существования
4. Max 1000 chars - может не хватить для S3 URLs
```

**Решение:**
```python
# Вариант A: Хранить только relative paths
local_video_path: "user_5/video/unprocessed/142_original.mp4"

# Вариант B: Хранить metadata + генерировать пути
class RecordingModel:
    id: int
    user_id: int
    
    @property
    def local_video_path(self) -> Path:
        return PathBuilder.video_original(self.user_id, self.id)
    
    @property
    def processed_audio_path(self) -> Path:
        return PathBuilder.audio_processed(self.user_id, self.id)

# Преимущества:
✅ Consistency
✅ Easy migration to S3
✅ No DB updates needed
```

**Impact:** Medium (architecture, но не urgent)

---

### 10. Нет atomic operations

**Проблема:**
```python
# api/tasks/processing.py:355
recording.processed_audio_path = str(audio_path)
# ❌ Если следующая операция упадет:
# - Путь сохранен в БД
# - Но файл может быть incomplete/corrupted

# Race condition:
# 1. FFmpeg создает файл
# 2. Сохраняем путь в БД
# 3. FFmpeg падает
# 4. Файл incomplete, но путь в БД есть
```

**Решение:**
```python
async def save_processed_audio(recording, audio_path):
    # 1. Create temp file
    temp_path = audio_path.with_suffix(".tmp")
    
    # 2. Process (FFmpeg)
    await process_audio(temp_path)
    
    # 3. Verify integrity
    if not verify_audio_file(temp_path):
        raise ValueError("Audio file corrupted")
    
    # 4. Atomic rename
    temp_path.rename(audio_path)
    
    # 5. Only then save to DB
    recording.processed_audio_path = str(audio_path)
```

**Impact:** Medium (reliability)

---

## 🎯 Приоритизация

| Проблема | Приоритет | Impact | Effort | ROI |
|----------|-----------|--------|--------|-----|
| #3: Orphaned files | 🔴 Critical | ⭐⭐⭐⭐⭐ | 2ч | ⭐⭐⭐⭐⭐ |
| #6: Нет cleanup | 🔴 Critical | ⭐⭐⭐⭐⭐ | 3ч | ⭐⭐⭐⭐⭐ |
| #7: Quota tracking | 🔴 Critical | ⭐⭐⭐⭐⭐ | 3ч | ⭐⭐⭐⭐⭐ |
| #4: Display_name files | 🟠 High | ⭐⭐⭐⭐ | 4ч | ⭐⭐⭐⭐ |
| #2: Thumbnail duplication | 🟠 High | ⭐⭐⭐⭐ | 2ч | ⭐⭐⭐⭐ |
| #8: temp_processing | 🟠 High | ⭐⭐⭐ | 1ч | ⭐⭐⭐⭐ |
| #1: Audio dirs | 🟡 Medium | ⭐⭐⭐ | 2ч | ⭐⭐⭐ |
| #10: Atomic ops | 🟡 Medium | ⭐⭐⭐ | 3ч | ⭐⭐⭐ |
| #9: Paths as strings | 🟡 Medium | ⭐⭐ | 4ч | ⭐⭐ |
| #5: Legacy dirs | 🟢 Low | ⭐ | 1ч | ⭐⭐ |

---

## 📋 План действий

### Фаза 1: Critical Fixes (1 день)
1. ✅ Implement `FileManager` с lifecycle tracking
2. ✅ Fix `delete()` для удаления файлов
3. ✅ Automatic quota tracking
4. ✅ Celery cleanup tasks

### Фаза 2: Structure Optimization (1 день)
5. ✅ ID-based file naming
6. ✅ Thumbnail optimization (no copy)
7. ✅ Унифицировать audio directories
8. ✅ Cleanup legacy directories

### Фаза 3: Reliability (1 день)
9. ✅ Atomic file operations
10. ✅ File integrity verification
11. ✅ Error recovery mechanisms

---

## 🎯 Целевая структура

```
media/
├── templates/
│   └── thumbnails/              # Global templates (read-only)
│       ├── applied_python.png   # ~200KB each
│       └── ...                  # Total: ~5MB
└── user_{id}/
    ├── video/
    │   ├── unprocessed/
    │   │   └── {recording_id}_original.mp4
    │   ├── processed/
    │   │   └── {recording_id}_trimmed.mp4
    │   └── temp_processing/     # Auto-cleanup (24h)
    │       └── {recording_id}_temp_{uuid}.mp4
    ├── audio/
    │   └── {recording_id}_processed.mp3
    ├── transcriptions/
    │   └── {recording_id}/
    │       ├── master.json
    │       ├── topics_v1.json
    │       └── subtitles.srt
    └── thumbnails/              # User-specific ONLY
        └── custom_thumb_142.png # Only if user uploaded
```

**Преимущества:**
- ✅ Consistency (один путь к каждому типу файла)
- ✅ Predictability (можно сгенерировать путь по ID)
- ✅ No duplication (thumbnails fallback)
- ✅ Easy cleanup (по recording_id)
- ✅ S3-ready (легко мигрировать)

---

**Статус:** Ready for implementation  
**Следующий шаг:** Начать с Фазы 1 (Critical Fixes)
