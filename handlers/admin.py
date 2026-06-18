from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, ConstructionObject, Task
from keyboards import get_main_menu_keyboard, get_users_keyboard, get_objects_keyboard, get_cancel_keyboard
from config import settings
import logging

logger = logging.getLogger(__name__)
router = Router()


class AddUserStates(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_name = State()
    waiting_for_role = State()
    waiting_for_object = State()


class AddObjectStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()


@router.message(F.text == "👥 Пользователи")
async def cmd_users(message: Message):
    """Список пользователей"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(select(User))
        users = result.scalars().all()

        if not users:
            await message.answer("👥 Пока нет пользователей")
            return

        users_text = "👥 Список пользователей:\n\n"
        for user in users:
            role_emoji = {
                UserRole.OWNER: "👑",
                UserRole.GENERAL_DIRECTOR: "💼",
                UserRole.PTO: "📐",
                UserRole.FOREMAN: "👷",
                UserRole.ELECTRICIAN: "⚡",
                UserRole.WORKER: "🔨"
            }.get(user.role, "👤")

            users_text += f"{role_emoji} {user.full_name}\n"
            users_text += f"   ID: {user.telegram_id}\n"
            users_text += f"   Роль: {user.role.value}\n\n"

        await message.answer(users_text)


@router.message(F.text == "➕ Добавить пользователя")
async def cmd_add_user(message: Message, state: FSMContext):
    """Добавление пользователя"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может добавлять пользователей")
            return

        await message.answer(
            "Введите Telegram ID нового пользователя:\n"
            "(Узнать ID можно через @userinfobot)",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AddUserStates.waiting_for_telegram_id)


@router.message(AddUserStates.waiting_for_telegram_id)
async def process_user_telegram_id(message: Message, state: FSMContext):
    """Обработка Telegram ID"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление пользователя отменено", reply_markup=get_main_menu_keyboard(UserRole.OWNER))
        return

    try:
        telegram_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID")
        return

    await state.update_data(telegram_id=telegram_id)
    await message.answer(
        "✅ Telegram ID сохранён.\n\n"
        "Введите ФИО пользователя:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddUserStates.waiting_for_name)


@router.message(AddUserStates.waiting_for_name)
async def process_user_name(message: Message, state: FSMContext):
    """Обработка ФИО"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление пользователя отменено", reply_markup=get_main_menu_keyboard(UserRole.OWNER))
        return

    await state.update_data(full_name=message.text)
    await message.answer(
        "✅ ФИО сохранено.\n\n"
        "Выберите роль:\n\n"
        "👑 Владелец\n"
        "💼 Гендиректор\n"
        "📐 ПТО\n"
        "👷 Прораб\n"
        "⚡ Электрик\n"
        "🔨 Рабочий",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddUserStates.waiting_for_role)


@router.message(AddUserStates.waiting_for_role)
async def process_user_role(message: Message, state: FSMContext):
    """Обработка роли"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление пользователя отменено", reply_markup=get_main_menu_keyboard(UserRole.OWNER))
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
            result = await session.execute(select(ConstructionObject))
            objects = result.scalars().all()

            if not objects:
                # Создаём объект по умолчанию
                obj = ConstructionObject(name="Основной объект", address="Не указан")
                session.add(obj)
                await session.commit()
                await create_user(message, state, obj.id)
            else:
                await message.answer(
                    "Выберите объект:",
                    reply_markup=get_objects_keyboard(objects)
                )
                await state.set_state(AddUserStates.waiting_for_object)
    else:
        await create_user(message, state, None)


@router.callback_query(AddUserStates.waiting_for_object, F.data.startswith("object_"))
async def process_user_object(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора объекта"""
    object_id = int(callback.data.split("_")[1])
    await create_user(callback.message, state, object_id)
    await callback.answer()


async def create_user(message: Message, state: FSMContext, object_id: int | None):
    """Создание пользователя"""
    data = await state.get_data()

    async for session in get_db():
        user = User(
            telegram_id=data["telegram_id"],
            full_name=data["full_name"],
            role=data["role"],
            object_id=object_id
        )
        session.add(user)
        await session.commit()

        await message.answer(
            f"✅ Пользователь добавлен!\n\n"
            f"👤 {data['full_name']}\n"
            f"🆔 Telegram ID: {data['telegram_id']}\n"
            f"🎭 Роль: {data['role'].value}\n"
            f"🏗️ Объект: {object_id or 'Не назначен'}",
            reply_markup=get_main_menu_keyboard(UserRole.OWNER)
        )

        await state.clear()
        logger.info(f"New user created by admin: {data['telegram_id']}, role={data['role']}")


@router.message(F.text == "🏗️ Объекты")
async def cmd_objects(message: Message):
    """Список объектов"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(select(ConstructionObject))
        objects = result.scalars().all()

        if not objects:
            await message.answer("🏗️ Пока нет объектов")
            return

        objects_text = "🏗️ Список объектов:\n\n"
        for obj in objects:
            objects_text += f"#{obj.id} {obj.name}\n"
            if obj.address:
                objects_text += f"   📍 {obj.address}\n"
            objects_text += "\n"

        await message.answer(objects_text)


@router.message(F.text == "➕ Добавить объект")
async def cmd_add_object(message: Message, state: FSMContext):
    """Добавление объекта"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может добавлять объекты")
            return

        await message.answer(
            "Введите название объекта:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(AddObjectStates.waiting_for_name)


@router.message(AddObjectStates.waiting_for_name)
async def process_object_name(message: Message, state: FSMContext):
    """Обработка названия объекта"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление объекта отменено", reply_markup=get_main_menu_keyboard(UserRole.OWNER))
        return

    await state.update_data(name=message.text)
    await message.answer(
        "✅ Название сохранено.\n\n"
        "Введите адрес (или '-' чтобы пропустить):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddObjectStates.waiting_for_address)


@router.message(AddObjectStates.waiting_for_address)
async def process_object_address(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка адреса и создание объекта"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление объекта отменено", reply_markup=get_main_menu_keyboard(UserRole.OWNER))
        return

    data = await state.get_data()
    address = message.text if message.text != "-" else None

    obj = ConstructionObject(
        name=data["name"],
        address=address
    )

    session.add(obj)
    await session.commit()

    await message.answer(
        f"✅ Объект добавлен!\n\n"
        f"🏗️ {data['name']}\n"
        f"📍 {address or 'Адрес не указан'}",
        reply_markup=get_main_menu_keyboard(UserRole.OWNER)
    )

    await state.clear()


@router.message(F.text == "📈 Статистика")
async def cmd_detailed_stats(message: Message):
    """Детальная статистика"""
    async for session in get_db():
        from sqlalchemy import select, func

        # Статистика пользователей
        result = await session.execute(
            select(User.role, func.count(User.id)).group_by(User.role)
        )
        user_stats = result.all()

        # Статистика задач
        result = await session.execute(
            select(Task.status, func.count(Task.id)).group_by(Task.status)
        )
        task_stats = result.all()

        # Статистика объектов
        result = await session.execute(
            select(ConstructionObject.name, func.count(Task.id))
            .join(Task, ConstructionObject.id == Task.object_id)
            .group_by(ConstructionObject.name)
        )
        object_stats = result.all()

        stats_text = "📈 Детальная статистика:\n\n"

        stats_text += "👥 Пользователи по ролям:\n"
        for role, count in user_stats:
            stats_text += f"  {role.value}: {count}\n"

        stats_text += "\n📋 Задачи по статусам:\n"
        for status, count in task_stats:
            stats_text += f"  {status}: {count}\n"

        stats_text += "\n🏗️ Задачи по объектам:\n"
        for name, count in object_stats:
            stats_text += f"  {name}: {count}\n"

        await message.answer(stats_text)