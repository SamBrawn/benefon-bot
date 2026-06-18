from typing import Optional
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import UserRole


class PermissionChecker:
    """Проверка прав доступа для разных ролей"""

    @staticmethod
    def is_owner(role: UserRole) -> bool:
        return role == UserRole.OWNER

    @staticmethod
    def is_director(role: UserRole) -> bool:
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]

    @staticmethod
    def is_pto(role: UserRole) -> bool:
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO]

    @staticmethod
    def is_foreman(role: UserRole) -> bool:
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]

    @staticmethod
    def is_worker(role: UserRole) -> bool:
        return role in [UserRole.ELECTRICIAN, UserRole.WORKER]

    @staticmethod
    def can_create_tasks(role: UserRole) -> bool:
        """Может создавать задачи"""
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]

    @staticmethod
    def can_approve_tasks(role: UserRole) -> bool:
        """Может утверждать задачи"""
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]

    @staticmethod
    def can_manage_materials(role: UserRole) -> bool:
        """Может управлять материалами"""
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO]

    @staticmethod
    def can_manage_tools(role: UserRole) -> bool:
        """Может управлять инструментами"""
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]

    @staticmethod
    def can_view_reports(role: UserRole) -> bool:
        """Может просматривать отчёты"""
        return role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]

    @staticmethod
    def can_approve_orders(role: UserRole) -> bool:
        """Может утверждать заявки"""
        return role in [UserRole.OWNER, UserRole.PTO]


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    """Получить пользователя по Telegram ID"""
    from models import User
    from sqlalchemy import select
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


def require_role(*allowed_roles: UserRole):
    """Декоратор для проверки роли пользователя"""
    def decorator(func):
        async def wrapper(message: Message, *args, **kwargs):
            async for session in get_db():
                user = await get_user_by_telegram_id(session, message.from_user.id)
                if not user:
                    await message.answer("❌ Вы не зарегистрированы. Используйте /start")
                    return
                
                if user.role not in allowed_roles:
                    await message.answer("❌ У вас нет прав для выполнения этой команды")
                    return
                
                kwargs['user'] = user
                kwargs['session'] = session
                return await func(message, *args, **kwargs)
        return wrapper
    return decorator