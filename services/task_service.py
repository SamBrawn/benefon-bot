from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from models import Task, TaskStatus, TaskStatusHistory, User, SalaryLog
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TaskService:
    """Сервис для управления задачами"""

    @staticmethod
    async def create_task(
        session: AsyncSession,
        title: str,
        assigned_to: int,
        assigned_by: int,
        description: Optional[str] = None,
        work_type: Optional[str] = None,
        cost: Optional[float] = None,
        deadline: Optional[datetime] = None,
        object_id: Optional[int] = None
    ) -> Task:
        """Создание новой задачи"""
        task = Task(
            title=title,
            description=description,
            work_type=work_type,
            cost=cost,
            deadline=deadline,
            assigned_to=assigned_to,
            assigned_by=assigned_by,
            object_id=object_id,
            status=TaskStatus.ASSIGNED
        )

        session.add(task)
        await session.commit()
        await session.refresh(task)

        # Создаём запись в истории
        history = TaskStatusHistory(
            task_id=task.id,
            old_status=None,
            new_status=TaskStatus.ASSIGNED,
            changed_by=assigned_by
        )
        session.add(history)
        await session.commit()

        logger.info(f"Task created: {task.id}, title={title}")
        return task

    @staticmethod
    async def get_task(session: AsyncSession, task_id: int) -> Optional[Task]:
        """Получение задачи по ID"""
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_tasks_for_user(session: AsyncSession, telegram_id: int) -> list[Task]:
        """Получение задач пользователя"""
        result = await session.execute(
            select(Task).where(
                (Task.assigned_to == telegram_id) |
                (Task.assigned_by == telegram_id)
            ).order_by(Task.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def update_task_status(
        session: AsyncSession,
        task_id: int,
        new_status: TaskStatus,
        changed_by: int
    ) -> Optional[Task]:
        """Обновление статуса задачи"""
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task:
            return None

        old_status = task.status
        task.status = new_status

        # Создаём запись в истории
        history = TaskStatusHistory(
            task_id=task_id,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by
        )
        session.add(history)

        # Если задача оплачена, создаём запись в salary_log
        if new_status == TaskStatus.PAID_BY_DIRECTOR and task.cost:
            salary = SalaryLog(
                user_id=task.assigned_to,
                task_id=task_id,
                amount=task.cost
            )
            session.add(salary)

        await session.commit()
        await session.refresh(task)

        logger.info(f"Task {task_id} status changed: {old_status} -> {new_status}")
        return task

    @staticmethod
    async def get_tasks_for_report(session: AsyncSession, limit: int = 50) -> list[Task]:
        """Получение задач для отчёта"""
        result = await session.execute(
            select(Task).order_by(Task.created_at.desc()).limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def get_task_stats(session: AsyncSession, telegram_id: int) -> dict:
        """Статистика задач пользователя"""
        # Всего задач
        result = await session.execute(
            select(func.count(Task.id)).where(Task.assigned_to == telegram_id)
        )
        total = result.scalar_one()

        # По статусам
        result = await session.execute(
            select(Task.status, func.count(Task.id))
            .where(Task.assigned_to == telegram_id)
            .group_by(Task.status)
        )
        by_status = {status: count for status, count in result.all()}

        return {
            "total": total,
            "by_status": by_status
        }