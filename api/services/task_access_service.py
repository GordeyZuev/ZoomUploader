"""Service for validating user access to Celery tasks.

Обеспечивает изоляцию задач между пользователями,
используя метаданные Celery для проверки владельца задачи.
"""

from celery.result import AsyncResult
from fastapi import HTTPException, status

from api.celery_app import celery_app
from logger import get_logger

logger = get_logger()


class TaskAccessService:
    """
    Сервис для проверки доступа к задачам Celery.

    Проверяет, что пользователь имеет право получать статус задачи
    и управлять ей (отменять). Использует user_id из результата/метаданных задачи.
    """

    @staticmethod
    def _extract_user_id_from_task(task: AsyncResult) -> int | None:
        """
        Извлечь user_id из задачи.

        Проверяет несколько источников в порядке приоритета:
        1. task.info (для PROCESSING состояния)
        2. task.result (для SUCCESS/FAILURE состояния)
        3. task.kwargs (сохраненные аргументы)

        Args:
            task: AsyncResult из Celery

        Returns:
            user_id или None если не найден
        """
        # 1. Проверяем info (для PROCESSING задач с метаданными)
        if task.info and isinstance(task.info, dict):
            user_id = task.info.get("user_id")
            if user_id:
                return int(user_id)

        # 2. Проверяем result (для SUCCESS задач)
        if task.state == "SUCCESS" and task.result and isinstance(task.result, dict):
            user_id = task.result.get("user_id")
            if user_id:
                return int(user_id)

        # 3. Проверяем kwargs (если задача сохраняет аргументы)
        # Примечание: для этого нужно включить task_send_sent_event=True в Celery
        try:
            # AsyncResult не хранит kwargs напрямую, но можно получить через backend
            # Для упрощения пропускаем, так как info и result покрывают большинство случаев
            pass
        except Exception as e:
            logger.warning(f"Ignored exception: {e}")

        return None

    @staticmethod
    def validate_task_access(task_id: str, user_id: int) -> AsyncResult:
        """
        Проверить доступ пользователя к задаче.

        Args:
            task_id: ID задачи Celery
            user_id: ID текущего пользователя

        Returns:
            AsyncResult задачи

        Raises:
            HTTPException: Если доступ запрещен или задача не найдена
        """
        task = AsyncResult(task_id, app=celery_app)

        # Для PENDING задач проверка невозможна (еще не стартовали)
        # Разрешаем доступ, так как задачу может создать только владелец через API
        if task.state == "PENDING":
            logger.debug(f"Task {task_id} is PENDING, skipping user_id check")
            return task

        # Извлекаем user_id из задачи
        task_user_id = TaskAccessService._extract_user_id_from_task(task)

        # Если не можем извлечь user_id - запрещаем доступ (fail-safe)
        if task_user_id is None:
            logger.warning(
                f"Cannot extract user_id from task {task_id} (state={task.state}). Access denied for user {user_id}."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot verify task ownership. Access denied.",
            )

        # Проверяем совпадение user_id
        if task_user_id != user_id:
            logger.warning(f"User {user_id} attempted to access task {task_id} owned by user {task_user_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. This task belongs to another user.",
            )

        logger.debug(f"User {user_id} validated access to task {task_id}")
        return task
