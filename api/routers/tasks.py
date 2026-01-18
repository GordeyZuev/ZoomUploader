"""Celery task status endpoints"""

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth.dependencies import get_current_user
from api.schemas.task import TaskCancelResponse, TaskStatusResponse
from api.services.task_access_service import TaskAccessService
from database.auth_models import UserModel

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    current_user: UserModel = Depends(get_current_user),
) -> TaskStatusResponse:
    """
    Get task status by ID.

    Args:
        task_id: ID of task from Celery
        current_user: Current authenticated user

    Returns:
        Information about task status with progress

    Task statuses:
        - PENDING: task is in queue, not yet started
        - PROCESSING: task is being executed (with progress 0-100)
        - SUCCESS: task completed successfully
        - FAILURE: task completed with an error
        - RETRY: task will be retried

    Security:
        Validates that the task belongs to the current user
    """
    # Validate user access to task (multi-tenancy isolation)
    task = TaskAccessService.validate_task_access(task_id, current_user.id)

    if task.state == "PENDING":
        # Task in queue
        return TaskStatusResponse(
            task_id=task_id,
            state="PENDING",
            status="Task is pending in queue",
            progress=0,
            result=None,
            error=None,
        )

    if task.state == "PROCESSING":
        # Task is being executed
        info = task.info or {}
        return TaskStatusResponse(
            task_id=task_id,
            state="PROCESSING",
            status=info.get("status", "Processing..."),
            progress=info.get("progress", 0),
            result=None,
            error=None,
        )

    if task.state == "SUCCESS":
        # Task completed successfully
        return TaskStatusResponse(
            task_id=task_id,
            state="SUCCESS",
            status="Task completed successfully",
            progress=100,
            result=task.result,
            error=None,
        )

    if task.state == "FAILURE":
        # Task completed with an error
        error_info = str(task.info) if task.info else "Unknown error"
        return TaskStatusResponse(
            task_id=task_id,
            state="FAILURE",
            status="Task failed",
            progress=0,
            result=None,
            error=error_info,
        )

    if task.state == "RETRY":
        # Task will be retried
        info = task.info or {}
        return TaskStatusResponse(
            task_id=task_id,
            state="RETRY",
            status="Task is retrying",
            progress=0,
            result=None,
            error=str(info),
        )

    # Unknown status
    return TaskStatusResponse(
        task_id=task_id,
        state=task.state,
        status=f"Unknown state: {task.state}",
        progress=0,
        result=None,
        error=None,
    )


@router.delete("/{task_id}", response_model=TaskCancelResponse)
async def cancel_task(
    task_id: str,
    current_user: UserModel = Depends(get_current_user),
) -> TaskCancelResponse:
    """
    Cancel task.

    Args:
        task_id: ID of task from Celery
        current_user: Current authenticated user

    Returns:
        Result of cancellation

    Note:
        - Tasks that are already being executed may not be cancelled immediately
        - PENDING tasks will be cancelled

    Security:
        Validates that the task belongs to the current user
    """
    # Validate user access to task (multi-tenancy isolation)
    task = TaskAccessService.validate_task_access(task_id, current_user.id)

    if task.state in ["SUCCESS", "FAILURE"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel task in state {task.state}",
        )

    # Cancel task
    task.revoke(terminate=True, signal="SIGKILL")

    return TaskCancelResponse(
        task_id=task_id,
        status="cancelled",
        message="Task cancellation requested",
    )
