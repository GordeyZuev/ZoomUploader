"""Celery configuration for async task processing"""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from celery import Celery  # noqa: E402
from celery.signals import task_failure, task_postrun, task_prerun  # noqa: E402

from api.config import get_settings  # noqa: E402
from config.settings import settings as app_settings  # noqa: E402

settings = get_settings()
database_url = (
    f"postgresql://{app_settings.database.username}:{app_settings.database.password}"
    f"@{app_settings.database.host}:{app_settings.database.port}/{app_settings.database.database}"
)

celery_app = Celery(
    "zoom_publishing",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "api.tasks.processing",
        "api.tasks.upload",
        "api.tasks.automation",
        "api.tasks.maintenance",
        "api.tasks.sync_tasks",
        "api.tasks.template",
    ],
)

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
    beat_dburi=database_url,  # Database URI for celery-sqlalchemy-scheduler
)

# Настройка очередей
celery_app.conf.task_routes = {
    "api.tasks.processing.*": {"queue": "processing"},
    "api.tasks.upload.*": {"queue": "upload"},
    "api.tasks.automation.*": {"queue": "automation"},
    "api.tasks.maintenance.*": {"queue": "maintenance"},
    "api.tasks.sync.*": {"queue": "processing"},  # Sync tasks use processing queue
    "api.tasks.template.*": {"queue": "processing"},  # Template tasks use processing queue
}

# Приоритеты очередей
celery_app.conf.broker_transport_options = {
    "priority_steps": list(range(10)),  # 0-9, где 9 - наивысший приоритет
    "sep": ":",
    "queue_order_strategy": "priority",
}

# Celery Beat Schedule для периодических задач
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "cleanup-expired-tokens": {
        "task": "maintenance.cleanup_expired_tokens",
        "schedule": crontab(hour=3, minute=0),  # Каждый день в 3:00 UTC
    },
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
