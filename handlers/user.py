from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, ConstructionObject
from keyboards import get_main_menu_keyboard, get_cancel_keyboard
from config import settings
import logging

logger = logging.getLogger(__name__)
router = Router()


class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_role = State()
    waiting_for_object = State()


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    async for session in get_db():
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user:
            # Пользователь уже зарегистрирован
            await message.answer(
                f"👋 С возвращением, {user.full_name}!\n"
                f"Ваша роль: {get_role_name(user.role)}",
                reply_markup=get_main_menu_keyboard(user.role)
            )
        else:
            # Новая регистрация
            # Проверяем, является ли пользователь админом
            if message.from_user.id in settings.admin_list:
                role = UserRole.OWNER
                await register_user(message, role, None, state)
            else:
                # Запрашиваем ФИО
                await message.answer(
                    "👋 Добро пожаловать!\n"
                    "Пожалуйста, введите ваше ФИО:",
                    reply_markup=get_cancel_keyboard()
                )
                await state.set_state(RegistrationStates.waiting_for_name)


@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """Обработка ФИО"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Регистрация отменена", reply_markup=None)
        return

    await state.update_data(full_name=message.text)
    await message.answer(
        "✅ ФИО сохранено.\n"
        "Теперь выберите вашу роль:\n\n"
        "👑 Владелец\n"
        "💼 Гендиректор\n"
        "📐 ПТО\n"
        "👷 Прораб\n"
        "⚡ Электрик\n"
        "🔨 Рабочий",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(RegistrationStates.waiting_for_role)


@router.message(RegistrationStates.waiting_for_role)
async def process_role(message: Message, state: FSMContext):
    """Обработка роли"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Регистрация отменена", reply_markup=None)
        return

    role_map = {
        "👑 Владелец": UserRole.OWNER,
        "💼 Гендиректор": UserRole.GENERAL_DIRECTOR,
        "📐 ПТО": UserRole.PTO,
        "👷 Прораб": UserRole.FOREMAN,
        "⚡ Электрик": UserRole.ELECTRICIAN,
        "🔨 Рабочий": UserRole.WORKER,
    }

    role = role_map.get(message.text)
    if not role:
        await message.answer("❌ Неверная роль. Выберите из списка:")
        return

    await state.update_data(role=role)

    # Если роль не рабочий/электрик, запрашиваем объект
    if role in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
        async for session in get_db():
            from sqlalchemy import select
            result = await session.execute(select(ConstructionObject).where(ConstructionObject.is_active == True))
            objects = result.scalars().all()

            if not objects:
                # Создаём объект по умолчанию
                obj = ConstructionObject(name="Основной объект", address="Не указан")
                session.add(obj)
                await session.commit()
                await register_user(message, role, obj.id, state)
            else:
                await message.answer(
                    "Выберите объект:",
                    reply_markup=get_objects_keyboard(objects)
                )
                await state.set_state(RegistrationStates.waiting_for_object)
    else:
        await register_user(message, role, None, state)


@router.callback_query(RegistrationStates.waiting_for_object, F.data.startswith("object_"))
async def process_object(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора объекта"""
    object_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    role = data.get("role")

    await register_user(callback.message, role, object_id, state)
    await callback.answer()


async def register_user(message: Message, role: UserRole, object_id: int | None, state: FSMContext):
    """Регистрация пользователя"""
    data = await state.get_data()
    full_name = data.get("full_name", message.from_user.full_name)

    async for session in get_db():
        user = User(
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            full_name=full_name,
            role=role,
            object_id=object_id
        )
        session.add(user)
        await session.commit()

        await message.answer(
            f"✅ Регистрация завершена!\n\n"
            f"👤 {full_name}\n"
            f"🎭 Роль: {get_role_name(role)}\n"
            f"🏗️ Объект: {object_id or 'Не назначен'}",
            reply_markup=get_main_menu_keyboard(role)
        )

        await state.clear()
        logger.info(f"New user registered: {message.from_user.id}, role={role}")


@router.message(F.text == "🌐 Веб-панель")
async def cmd_web_login(message: Message):
    """Генерация токена для веб-панели"""
    async for session in get_db():
        from sqlalchemy import select
        import uuid
        from datetime import datetime, timedelta

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы. Используйте /start")
            return

        # Создаём токен
        token = uuid.uuid4()
        expires_at = datetime.utcnow() + timedelta(hours=24)

        from models import WebToken
        web_token = WebToken(
            user_id=user.telegram_id,
            token=token,
            expires_at=expires_at
        )
        session.add(web_token)
        await session.commit()

        # Отправляем ссылку
        web_url = f"{settings.WEB_BASE_URL}/web_login?token={token}"
        await message.answer(
            f"🔗 Ваша ссылка для входа в веб-панель (действительна 24 часа):\n\n"
            f"{web_url}"
        )


@router.message(F.text == "📊 Статистика")
async def cmd_stats(message: Message):
    """Показать статистику"""
    async for session in get_db():
        from sqlalchemy import select, func
        from models import Task

        # Статистика задач
        result = await session.execute(
            select(Task.status, func.count(Task.id))
            .group_by(Task.status)
        )
        stats = result.all()

        stats_text = "📊 Статистика задач:\n\n"
        for status, count in stats:
            stats_text += f"{status}: {count}\n"

        await message.answer(stats_text)


def get_role_name(role: UserRole) -> str:
    """Получить название роли на русском"""
    names = {
        UserRole.OWNER: "👑 Владелец",
        UserRole.GENERAL_DIRECTOR: "💼 Гендиректор",
        UserRole.PTO: "📐 ПТО",
        UserRole.FOREMAN: "👷 Прораб",
        UserRole.ELECTRICIAN: "⚡ Электрик",
        UserRole.WORKER: "🔨 Рабочий",
    }
    return names.get(role, role.value)