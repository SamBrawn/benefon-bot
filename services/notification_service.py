from aiogram import Bot
from aiogram.types import Message, FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, Task, MaterialOrder
from config import settings
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис для отправки уведомлений"""

    def __init__(self):
        self.bot = Bot(token=settings.BOT_TOKEN)

    async def send_message(self, user_id: int, text: str):
        """Отправка текстового сообщения"""
        try:
            await self.bot.send_message(user_id, text)
            logger.info(f"Message sent to {user_id}")
        except Exception as e:
            logger.error(f"Failed to send message to {user_id}: {e}")

    async def send_document(self, user_id: int, file_path: str, caption: str = ""):
        """Отправка документа"""
        try:
            document = FSInputFile(file_path)
            await self.bot.send_document(user_id, document, caption=caption)
            logger.info(f"Document sent to {user_id}: {file_path}")
        except Exception as e:
            logger.error(f"Failed to send document to {user_id}: {e}")

    async def send_photo(self, user_id: int, photo_path: str, caption: str = ""):
        """Отправка фото"""
        try:
            photo = FSInputFile(photo_path)
            await self.bot.send_photo(user_id, photo, caption=caption)
            logger.info(f"Photo sent to {user_id}")
        except Exception as e:
            logger.error(f"Failed to send photo to {user_id}: {e}")

    async def notify_task_assigned(self, task: Task):
        """Уведомление о новой задаче"""
        text = (
            f"📋 Вам назначена новая задача!\n\n"
            f"📌 {task.title}\n"
            f"📝 {task.description or 'Без описания'}\n"
            f"🔧 {task.work_type or 'Не указан'}\n"
            f"💰 {task.cost or 0} руб.\n"
            f"📅 {task.deadline.strftime('%d.%m.%Y') if task.deadline else 'Без дедлайна'}"
        )
        await self.send_message(task.assigned_to, text)

    async def notify_task_status_changed(self, task: Task, old_status, new_status):
        """Уведомление о смене статуса"""
        text = (
            f"📋 Статус задачи #{task.id} изменён!\n\n"
            f"📌 {task.title}\n"
            f"📊 {old_status} → {new_status}"
        )
        await self.send_message(task.assigned_to, text)

    async def send_daily_digest(self):
        """Ежедневный дайджест в 09:00"""
        async for session in get_db():
            from sqlalchemy import select, func

            # Получаем статистику
            result = await session.execute(
                select(func.count(Task.id)).where(Task.status == TaskStatus.ASSIGNED)
            )
            assigned_count = result.scalar_one()

            result = await session.execute(
                select(func.count(Task.id)).where(Task.status == TaskStatus.IN_PROGRESS)
            )
            in_progress_count = result.scalar_one()

            # Отправляем всем пользователям
            result = await session.execute(select(User))
            users = result.scalars().all()

            for user in users:
                text = (
                    f"☀️ Доброе утро!\n\n"
                    f"📊 Статистика на {datetime.now().strftime('%d.%m.%Y')}:\n"
                    f"📌 Назначено задач: {assigned_count}\n"
                    f"⚙️ В работе: {in_progress_count}\n\n"
                    f"Хорошего рабочего дня! 🏗️"
                )
                await self.send_message(user.telegram_id, text)

    async def send_owner_report(self):
        """Отчёт владельцу в 20:00"""
        async for session in get_db():
            from sqlalchemy import select, func

            # Статистика за день
            result = await session.execute(
                select(func.count(Task.id)).where(
                    Task.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
                )
            )
            new_tasks = result.scalar_one()

            result = await session.execute(
                select(func.count(Task.id)).where(Task.status == TaskStatus.PAID_BY_DIRECTOR)
            )
            paid_tasks = result.scalar_one()

            # Получаем владельца
            result = await session.execute(
                select(User).where(User.role == UserRole.OWNER)
            )
            owner = result.scalar_one_or_none()

            if owner:
                text = (
                    f"📈 Ежедневный отчёт ({datetime.now().strftime('%d.%m.%Y')}):\n\n"
                    f"📋 Новых задач: {new_tasks}\n"
                    f"💰 Оплачено задач: {paid_tasks}\n\n"
                    f"Подробности в веб-панели."
                )
                await self.send_message(owner.telegram_id, text)

    async def notify_material_critical(self, material):
        """Уведомление о критическом остатке"""
        text = (
            f"⚠️ КРИТИЧЕСКИЙ ОСТАТОК МАТЕРИАЛА!\n\n"
            f"📌 {material.name}\n"
            f"📦 Остаток: {material.quantity} {material.unit.value}\n"
            f"📊 Начальное: {material.initial_quantity} {material.unit.value}\n\n"
            f"Срочно пополните запасы!"
        )

        # Отправляем ПТО и владельцу
        async for session in get_db():
            from sqlalchemy import select

            result = await session.execute(
                select(User).where(User.role.in_([UserRole.OWNER, UserRole.PTO]))
            )
            admins = result.scalars().all()

            for admin in admins:
                await self.send_message(admin.telegram_id, text)

    async def notify_order_status_changed(self, order):
        """Уведомление об изменении статуса заявки"""
        status_names = {
            "pending_pto": "Ожидает ПТО",
            "pending_owner": "Ожидает владельца",
            "approved": "Утверждена",
            "rejected": "Отклонена"
        }

        text = (
            f"📝 Статус заявки #{order.id} изменён!\n"
            f"📊 Новый статус: {status_names.get(order.status, order.status)}\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

        # Уведомляем создателя заявки
        await self.send_message(order.created_by, text)

    async def notify_tool_assigned(self, tool, user):
        """Уведомление о назначении инструмента"""
        text = (
            f"🔧 Вам назначен инструмент!\n\n"
            f"📌 {tool.name}\n"
            f"📋 Инвентарный номер: {tool.inventory_number}"
        )
        await self.send_message(user.telegram_id, text)