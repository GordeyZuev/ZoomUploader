# Task Migration Guide: Adding user_id to metadata

Руководство по обновлению всех Celery задач для поддержки multi-tenancy.

## 🎯 Цель

Передавать `user_id` в метаданные КАЖДОЙ задачи для проверки доступа в Tasks API.

## 📦 Новый базовый класс: BaseTask

Все задачи теперь наследуются от `BaseTask` (через специализированные классы),
который автоматически добавляет `user_id` в метаданные.

### 1. `self.update_progress()`

Заменяет стандартный `self.update_state()` с автоматическим добавлением `user_id`.

```python
# ❌ СТАРЫЙ КОД
self.update_state(
    state='PROCESSING',
    meta={
        'progress': 50,
        'status': 'Processing video...',
        'step': 'trim'
    }
)

# ✅ НОВЫЙ КОД  
self.update_progress(
    user_id=user_id,
    progress=50,
    status='Processing video...',
    step='trim'
)
```

### 2. `self.build_result()`

Создает результат задачи с `user_id`.

```python
# ❌ СТАРЫЙ КОД
return {
    "task_id": self.request.id,
    "status": "completed",
    "recording_id": recording_id,
    "result": {...}
}

# ✅ НОВЫЙ КОД
return self.build_result(
    user_id=user_id,
    status="completed",
    recording_id=recording_id,
    result={...}
)
```

## 📝 Пошаговая миграция файла

### Шаг 1: Обновить импорт базового класса

Все базовые классы задач теперь в `api/tasks/base.py`.

```python
# ❌ СТАРЫЙ КОД
from celery import Task

class ProcessingTask(Task):
    ...

# ✅ НОВЫЙ КОД
from api.tasks.base import ProcessingTask  # Или UploadTask, SyncTask, TemplateTask
```

### Шаг 2: Найти все `self.update_state()`

```bash
# Поиск в файле
grep -n "self.update_state" api/tasks/YOUR_FILE.py
```

### Шаг 3: Заменить каждый вызов

**Правила замены:**
1. Первый параметр - `self`
2. Второй параметр - `user_id=user_id`
3. `state=` остается как есть
4. Из `meta={}` извлекаем все поля как отдельные параметры

**Пример:**

```python
# ДО
self.update_state(
    state='PROCESSING',
    meta={
        'progress': 75,
        'status': 'Extracting topics...',
        'step': 'topics',
        'model': 'llama-3.3'
    }
)

# ПОСЛЕ
self.update_progress(
    user_id=user_id,
    progress=75,
    status='Extracting topics...',
    step='topics',
    model='llama-3.3'  # extra kwargs становятся частью meta
)
```

### Шаг 4: Обновить return в конце задачи

```python
# ДО
return {
    "task_id": self.request.id,
    "status": "completed",
    "recording_id": recording_id,
    "video_url": video_url,
}

# ПОСЛЕ
return self.build_result(
    user_id=user_id,
    status="completed",
    recording_id=recording_id,
    video_url=video_url,
)
```

## 🗂️ Файлы для миграции

### Высокий приоритет (используются в API):

- [ ] `api/tasks/processing.py`
  - [ ] `trim_video_task`
  - [ ] `transcribe_recording_task`
  - [ ] `batch_transcribe_recording_task`
  - [ ] `extract_topics_task`
  - [ ] `generate_subtitles_task`
  - [ ] `process_recording_task`
  
- [ ] `api/tasks/upload.py`
  - [ ] `upload_recording_to_platform`
  
- [ ] `api/tasks/sync_tasks.py`
  - [ ] `sync_single_source_task`
  - [ ] `bulk_sync_sources_task`

### Средний приоритет (автоматизация):

- [ ] `api/tasks/automation.py`
  - [ ] `run_automation_job_task`
  - [ ] `dry_run_automation_job_task`
  
- [ ] `api/tasks/template.py`
  - [ ] `rematch_recordings_task`

### Низкий приоритет (maintenance):

- [ ] `api/tasks/maintenance.py`
  - Обычно не требуют multi-tenancy

## ✅ Checklist для каждой задачи

- [ ] Базовый класс импортируется из `api.tasks.base`
- [ ] Все `self.update_state()` заменены на `self.update_progress()`
- [ ] Return использует `self.build_result()`
- [ ] Проверено, что `user_id` передается во все вложенные функции
- [ ] Запущены линтеры (`make lint`)
- [ ] Протестировано вручную

## 🧪 Тестирование после миграции

```python
# 1. Запустить задачу
task = your_task.delay(recording_id=1, user_id=42)

# 2. Проверить метаданные
from celery.result import AsyncResult
result = AsyncResult(task.id)

# 3. Убедиться, что user_id присутствует
assert result.info.get('user_id') == 42  # для PROCESSING
assert result.result.get('user_id') == 42  # для SUCCESS
```

## 🚨 Возможные ошибки

### Ошибка: KeyError 'user_id' в nested функциях

**Проблема:**
```python
async def _async_helper(task_self, recording_id):  # ❌ нет user_id!
    update_task_state_with_user(
        task_self,
        user_id=user_id,  # ❌ user_id не определен
        ...
    )
```

**Решение:**
```python
async def _async_helper(task_self, recording_id, user_id):  # ✅
    update_task_state_with_user(
        task_self,
        user_id=user_id,  # ✅
        ...
    )
```

### Ошибка: user_id не в kwargs

**Проблема:**
Задача вызывается без `user_id`:
```python
task.delay(recording_id=1)  # ❌ нет user_id
```

**Решение:**
Всегда передавать `user_id`:
```python
task.delay(recording_id=1, user_id=ctx.user_id)  # ✅
```

## 📊 Прогресс миграции

Статус: **Частично выполнено**

- ✅ `download_recording_task` - мигрирована
- ⏳ Остальные задачи - в процессе

## 🔗 См. также

- [Multi-Tenancy Fixes](./MULTI_TENANCY_FIXES.md)
- [Task Access Service](../../api/services/task_access_service.py)
