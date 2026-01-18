# Architecture Decision: Multi-Tenancy в Celery Tasks

## Контекст

Необходимо обеспечить изоляцию задач между пользователями (multi-tenancy) для безопасного доступа к Tasks API.

## Рассмотренные варианты

### ❌ Вариант 1: Helper-функции

```python
# api/helpers/task_state_helper.py
def update_task_state_with_user(task_self, user_id, ...):
    task_self.update_state(...)

# Использование
update_task_state_with_user(self, user_id, ...)
```

**Проблемы:**
- Антипаттерн "Helper" - превращается в свалку разной логики
- Не очевидно, что это часть жизненного цикла задачи
- Нарушает инкапсуляцию - передаем self явно
- Усложняет code review (где helper, где бизнес-логика?)

### ✅ Вариант 2: Базовый класс BaseTask (ВЫБРАН)

```python
# api/tasks/base.py
class BaseTask(Task):
    """Base class for all application tasks."""
    
    def update_progress(self, user_id, progress, status, **kwargs):
        self.update_state(state="PROCESSING", meta={
            "user_id": user_id,
            "progress": progress,
            "status": status,
            **kwargs
        })

    def build_result(self, user_id, **data):
        return {"task_id": self.request.id, "user_id": user_id, **data}

# Использование
class ProcessingTask(BaseTask):
    pass

@celery_app.task(bind=True, base=ProcessingTask)
def my_task(self, user_id, ...):
    self.update_progress(user_id, 50, "Processing...")
    return self.build_result(user_id, result=...)
```

**Преимущества:**
- ✅ Чистая архитектура - логика в подходящем месте
- ✅ Инкапсуляция - методы класса, не внешние функции
- ✅ Наследование - естественное расширение Celery Task
- ✅ Типизация - IDE понимает методы класса
- ✅ Тестируемость - легко mock/patch методы
- ✅ DRY - один базовый класс для всех задач
- ✅ KISS - простая иерархия наследования

## Решение

Используем **Вариант 2**: Базовый класс `BaseTask`.

### Иерархия классов

```
Task (Celery)
  └── BaseTask (наш базовый)
        ├── ProcessingTask (download, trim, transcribe, etc.)
        ├── UploadTask (upload to platforms)
        ├── SyncTask (sync from sources)
        └── TemplateTask (template operations)
```

### API базового класса

```python
class BaseTask(Task):
    # Обновление прогресса с user_id
    def update_progress(user_id, progress, status, step=None, **extra_meta)
    
    # Формирование результата с user_id
    def build_result(user_id, status="completed", **data)
    
    # Hooks для логирования
    def on_failure(exc, task_id, args, kwargs, einfo)
    def on_retry(exc, task_id, args, kwargs, einfo)
    def on_success(retval, task_id, args, kwargs)
```

### Пример использования

```python
@celery_app.task(bind=True, base=ProcessingTask)
def process_recording_task(self, recording_id: int, user_id: int):
    # Вместо: self.update_state(state='PROCESSING', meta={...})
    self.update_progress(
        user_id=user_id,
        progress=50,
        status="Processing video...",
        step="trim"
    )
    
    result = do_processing()
    
    # Вместо: return {"task_id": self.request.id, ...}
    return self.build_result(
        user_id=user_id,
        status="completed",
        result=result
    )
```

## Последствия

### Положительные

- ✅ Чистая архитектура без helpers
- ✅ Автоматическая передача user_id в метаданные
- ✅ Легко расширяется на новые типы задач
- ✅ Понятная иерархия классов
- ✅ Меньше boilerplate кода

### Отрицательные

- ⚠️ Нужно обновить все существующие задачи
- ⚠️ Требует понимания наследования в Celery

## Связанные решения

- Создан `TaskAccessService` для проверки доступа к задачам через API
- Создан `ResourceAccessValidator` для проверки владения ресурсами
- Все сервисы (не helpers!) для централизованной бизнес-логики

## Принципы

1. **KISS**: Простая иерархия классов вместо утильных функций
2. **DRY**: Один базовый класс, переиспользуется везде
3. **SOLID**: Single Responsibility - каждый класс отвечает за свой тип задач
4. **Clean Architecture**: Логика в правильном слое (базовый класс задачи)

## Файлы

- `api/tasks/base.py` - базовые классы (✅ создан)
- `api/tasks/processing.py` - использует новый базовый класс (✅ обновлен)
- `api/tasks/upload.py` - использует новый базовый класс (✅ обновлен)
- `api/tasks/sync_tasks.py` - использует новый базовый класс (✅ обновлен)
- `api/tasks/template.py` - использует новый базовый класс (✅ обновлен)

## Ссылки

- [Multi-Tenancy Fixes](./MULTI_TENANCY_FIXES.md)
- [Task Migration Guide](./TASK_MIGRATION_GUIDE.md)
