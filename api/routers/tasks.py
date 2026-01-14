"""API endpoints для проверки статуса Celery задач."""

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status

from api.celery_app import celery_app
from api.schemas.task import TaskCancelResponse, TaskStatusResponse

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
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
        return TaskStatusResponse(
            task_id=task_id,
            state="PENDING",
            status="Task is pending in queue",
            progress=0,
            result=None,
            error=None,
        )

    elif task.state == "PROCESSING":
        # Задача выполняется
        info = task.info or {}
        return TaskStatusResponse(
            task_id=task_id,
            state="PROCESSING",
            status=info.get("status", "Processing..."),
            progress=info.get("progress", 0),
            result=None,
            error=None,
        )

    elif task.state == "SUCCESS":
        # Задача завершена успешно
        return TaskStatusResponse(
            task_id=task_id,
            state="SUCCESS",
            status="Task completed successfully",
            progress=100,
            result=task.result,
            error=None,
        )

    elif task.state == "FAILURE":
        # Задача завершена с ошибкой
        error_info = str(task.info) if task.info else "Unknown error"
        return TaskStatusResponse(
            task_id=task_id,
            state="FAILURE",
            status="Task failed",
            progress=0,
            result=None,
            error=error_info,
        )

    elif task.state == "RETRY":
        # Задача будет повторена
        info = task.info or {}
        return TaskStatusResponse(
            task_id=task_id,
            state="RETRY",
            status="Task is retrying",
            progress=0,
            result=None,
            error=str(info),
        )

    else:
        # Неизвестный статус
        return TaskStatusResponse(
            task_id=task_id,
            state=task.state,
            status=f"Unknown state: {task.state}",
            progress=0,
            result=None,
            error=None,
        )


@router.delete("/{task_id}", response_model=TaskCancelResponse)
async def cancel_task(task_id: str) -> TaskCancelResponse:
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

    return TaskCancelResponse(
        task_id=task_id,
        status="cancelled",
        message="Task cancellation requested",
    )
