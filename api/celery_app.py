"""Конфигурация Celery для асинхронной обработки задач."""

from celery import Celery
from celery.signals import task_failure, task_postrun, task_prerun

from api.config import get_settings

settings = get_settings()

# Создание Celery приложения
celery_app = Celery(
    "zoom_publishing",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["api.tasks.processing", "api.tasks.upload"],
)

# Конфигурация Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 час максимум на задачу
    task_soft_time_limit=3300,  # Мягкий лимит 55 минут
    worker_prefetch_multiplier=1,  # Брать по 1 задаче на воркера
    worker_max_tasks_per_child=50,  # Перезапуск воркера после 50 задач
    task_acks_late=True,  # Подтверждать выполнение после завершения
    task_reject_on_worker_lost=True,  # Отклонять при сбое воркера
    result_expires=86400,  # Результаты хранятся 24 часа
)

# Настройка очередей
celery_app.conf.task_routes = {
    "api.tasks.processing.*": {"queue": "processing"},
    "api.tasks.upload.*": {"queue": "upload"},
}

# Приоритеты очередей
celery_app.conf.broker_transport_options = {
    "priority_steps": list(range(10)),  # 0-9, где 9 - наивысший приоритет
    "sep": ":",
    "queue_order_strategy": "priority",
}


@task_prerun.connect
def task_prerun_handler(task_id, task, *args, **kwargs):
    """Обработчик перед запуском задачи."""
    print(f"[CELERY] Starting task {task.name} [{task_id}]")


@task_postrun.connect
def task_postrun_handler(task_id, task, *args, **kwargs):
    """Обработчик после выполнения задачи."""
    print(f"[CELERY] Completed task {task.name} [{task_id}]")


@task_failure.connect
def task_failure_handler(task_id, exception, *args, **kwargs):
    """Обработчик при ошибке задачи."""
    print(f"[CELERY] Failed task [{task_id}]: {exception}")
