"""Endpoints для управления и мониторинга Celery задач."""

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.celery_app import celery_app
from logger import logger

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


class TaskStatusResponse(BaseModel):
    """Ответ со статусом задачи."""

    task_id: str
    status: str
    result: dict | None = None
    error: str | None = None
    progress: dict | None = None


class TaskCancelResponse(BaseModel):
    """Ответ на отмену задачи."""

    task_id: str
    status: str
    message: str


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """
    Получить статус задачи по ID.

    Args:
        task_id: ID задачи Celery

    Returns:
        Статус задачи и результат (если завершена)

    Raises:
        HTTPException: Если задача не найдена
    """
    try:
        task_result = AsyncResult(task_id, app=celery_app)

        # Статусы Celery: PENDING, STARTED, RETRY, FAILURE, SUCCESS
        status_map = {
            "PENDING": "pending",
            "STARTED": "in_progress",
            "RETRY": "retrying",
            "FAILURE": "failed",
            "SUCCESS": "completed",
        }

        response = {
            "task_id": task_id,
            "status": status_map.get(task_result.state, task_result.state.lower()),
        }

        # Если задача завершена успешно
        if task_result.successful():
            response["result"] = task_result.result

        # Если задача провалилась
        elif task_result.failed():
            response["error"] = str(task_result.info)

        # Если задача выполняется (можно добавить прогресс)
        elif task_result.state == "STARTED":
            # Если задача поддерживает прогресс
            if hasattr(task_result.info, "get"):
                response["progress"] = task_result.info

        return TaskStatusResponse(**response)

    except Exception as e:
        logger.error(f"Error getting task status {task_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving task status: {str(e)}",
        )


@router.delete("/{task_id}", response_model=TaskCancelResponse)
async def cancel_task(task_id: str):
    """
    Отменить выполняющуюся задачу.

    Args:
        task_id: ID задачи Celery

    Returns:
        Подтверждение отмены

    Raises:
        HTTPException: Если задача не найдена или не может быть отменена
    """
    try:
        task_result = AsyncResult(task_id, app=celery_app)

        if task_result.state in ["SUCCESS", "FAILURE"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot cancel task in state: {task_result.state}",
            )

        # Отмена задачи
        celery_app.control.revoke(task_id, terminate=True, signal="SIGKILL")

        return TaskCancelResponse(task_id=task_id, status="cancelled", message="Task cancellation requested")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling task: {str(e)}",
        )


@router.get("/", response_model=dict)
async def get_active_tasks():
    """
    Получить список активных задач.

    Returns:
        Словарь с активными задачами по очередям
    """
    try:
        # Получение активных задач из Celery
        inspect = celery_app.control.inspect()

        active_tasks = inspect.active()
        scheduled_tasks = inspect.scheduled()
        reserved_tasks = inspect.reserved()

        return {
            "active": active_tasks or {},
            "scheduled": scheduled_tasks or {},
            "reserved": reserved_tasks or {},
        }

    except Exception as e:
        logger.error(f"Error getting active tasks: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving active tasks: {str(e)}",
        )


@router.get("/stats", response_model=dict)
async def get_task_stats():
    """
    Получить статистику по задачам.

    Returns:
        Статистика Celery
    """
    try:
        inspect = celery_app.control.inspect()

        stats = inspect.stats()
        active_queues = inspect.active_queues()

        return {"stats": stats or {}, "queues": active_queues or {}}

    except Exception as e:
        logger.error(f"Error getting task stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving task stats: {str(e)}",
        )
