"""API endpoints для проверки статуса Celery задач."""

from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status

from api.celery_app import celery_app

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


@router.get("/{task_id}")
async def get_task_status(task_id: str) -> dict[str, Any]:
    """
    Получить статус задачи по ID.

    Args:
        task_id: ID задачи из Celery

    Returns:
        Информация о статусе задачи с прогрессом

    Статусы задачи:
        - PENDING: задача в очереди, еще не началась
        - PROCESSING: задача выполняется (с прогрессом 0-100)
        - SUCCESS: задача завершена успешно
        - FAILURE: задача завершена с ошибкой
        - RETRY: задача будет повторена
    """
    task = AsyncResult(task_id, app=celery_app)

    if task.state == "PENDING":
        # Задача в очереди
        return {
            "task_id": task_id,
            "state": "PENDING",
            "status": "Task is pending in queue",
            "progress": 0,
            "result": None,
            "error": None,
        }

    elif task.state == "PROCESSING":
        # Задача выполняется
        info = task.info or {}
        return {
            "task_id": task_id,
            "state": "PROCESSING",
            "status": info.get("status", "Processing..."),
            "progress": info.get("progress", 0),
            "step": info.get("step", None),
            "result": None,
            "error": None,
        }

    elif task.state == "SUCCESS":
        # Задача завершена успешно
        return {
            "task_id": task_id,
            "state": "SUCCESS",
            "status": "Task completed successfully",
            "progress": 100,
            "result": task.result,
            "error": None,
        }

    elif task.state == "FAILURE":
        # Задача завершена с ошибкой
        error_info = str(task.info) if task.info else "Unknown error"
        return {
            "task_id": task_id,
            "state": "FAILURE",
            "status": "Task failed",
            "progress": 0,
            "result": None,
            "error": error_info,
        }

    elif task.state == "RETRY":
        # Задача будет повторена
        info = task.info or {}
        return {
            "task_id": task_id,
            "state": "RETRY",
            "status": "Task is retrying",
            "progress": 0,
            "result": None,
            "error": str(info),
        }

    else:
        # Неизвестный статус
        return {
            "task_id": task_id,
            "state": task.state,
            "status": f"Unknown state: {task.state}",
            "progress": 0,
            "result": None,
            "error": None,
        }


@router.delete("/{task_id}")
async def cancel_task(task_id: str) -> dict[str, Any]:
    """
    Отменить задачу.

    Args:
        task_id: ID задачи из Celery

    Returns:
        Результат отмены

    Note:
        - Задачи, которые уже выполняются, могут не отменится сразу
        - PENDING задачи будут отменены
    """
    task = AsyncResult(task_id, app=celery_app)

    if task.state in ["SUCCESS", "FAILURE"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in state {task.state}",
        )

    # Отменяем задачу
    task.revoke(terminate=True, signal="SIGKILL")

    return {
        "task_id": task_id,
        "status": "cancelled",
        "message": "Task cancellation requested",
    }


@router.get("/{task_id}/result")
async def get_task_result(task_id: str) -> dict[str, Any]:
    """
    Получить только результат задачи (блокирующий вызов).

    Args:
        task_id: ID задачи из Celery

    Returns:
        Результат выполнения задачи

    Note:
        Этот endpoint НЕ рекомендуется использовать, так как он блокирующий.
        Используйте GET /tasks/{task_id} для проверки статуса.
    """
    task = AsyncResult(task_id, app=celery_app)

    if not task.ready():
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail="Task is not ready yet. Use GET /tasks/{task_id} to check status.",
        )

    if task.failed():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Task failed: {task.info}",
        )

    return {
        "task_id": task_id,
        "result": task.result,
    }
