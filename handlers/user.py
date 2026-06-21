from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from database import get_db
from models import User
from keyboards import get_owner_keyboard, get_main_menu_keyboard as get_role_keyboard_from_keyboards
from datetime import datetime, date

router = Router()

# Главное меню (для незарегистрированных)
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои задачи")],
            [KeyboardButton(text="➕ Новая задача")],
            [KeyboardButton(text="📊 Отчёт")],
            [KeyboardButton(text="🔑 Веб-панель")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

# Меню для зарегистрированных (по роли)
def get_role_keyboard(role: str = None):
    keyboard = [
        [KeyboardButton(text="📋 Мои задачи")],
        [KeyboardButton(text="➕ Новая задача")],
    ]
    
    if role in ["owner", "general_director", "foreman", "pto"]:
        keyboard.append([KeyboardButton(text="📊 Отчёт")])
    
    if role in ["owner", "general_director", "foreman"]:
        keyboard.append([KeyboardButton(text="📦 Материалы")])
        keyboard.append([KeyboardButton(text="🔧 Инструменты")])
    
    if role == "owner":
        keyboard.append([KeyboardButton(text="👥 Управление командой")])
    
    keyboard.append([KeyboardButton(text="🔑 Веб-панель")])
    keyboard.append([KeyboardButton(text="👤 Мой профиль")])
    
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )


@router.message(Command("start"))
async def start(message: types.Message):
    # Проверяем инструктаж по ТБ
    from handlers.safety import require_safety_briefing
    if not await require_safety_briefing(message):
        return
    
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Для владельца используем специальную клавиатуру
            if user.role == "owner":
                keyboard = get_owner_keyboard()
            else:
                keyboard = get_role_keyboard(user.role)
            
            await message.answer(
                f"👋 С возвращением, {user.full_name}!\n\n"
                f"🏗️ Роль: {user.role}\n"
                f"🆔 ID: {user.telegram_id}\n\n"
                "Выберите действие:",
                reply_markup=keyboard
            )
        else:
            await message.answer(
                "👋 Добро пожаловать в Benefon Bot!\n\n"
                "🏗️ Строительная компания «Бенефон»\n\n"
                "❌ Вы не зарегистрированы.\n"
                "Обратитесь к владельцу для получения доступа.\n\n"
                "Доступные команды:\n"
                "/start — Главное меню\n"
                "/help — Помощь\n"
                "/web_login — Веб-панель",
                reply_markup=get_main_keyboard()
            )


@router.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "🤖 Benefon Bot — Помощь\n\n"
        "📋 Основные команды:\n"
        "/start — Главное меню\n"
        "/help — Помощь\n\n"
        "📌 Для всех:\n"
        "/my_tasks — Мои задачи\n"
        "/web_login — Веб-панель\n\n"
        "👷 Рабочий/Электрик:\n"
        "/start_task [id] — Начать задачу\n"
        "/submit_photo [id] — Сдать фото\n"
        "/my_salary — Моя зарплата\n\n"
        "👔 Прораб:\n"
        "/new_task — Создать задачу\n"
        "/approve_task [id] — Утвердить\n"
        "/reject_task [id] — Отклонить\n"
        "/add_material — Добавить материал\n"
        "/use_material — Списать материал\n"
        "/stock — Остатки\n"
        "/assign_tool — Закрепить инструмент\n"
        "/transfer_tool — Передать\n"
        "/new_order — Заявка на материалы\n\n"
        "👑 Гендиректор:\n"
        "/pay_task [id] — Оплатить\n"
        "/adjust_cost [id] [цена] — Изменить стоимость\n"
        "/gen_report — Отчёт\n\n"
        "👑 Владелец:\n"
        "/add_user — Добавить сотрудника\n"
        "/add_object — Добавить объект\n"
        "/owner_approve [id] — Утвердить заявку"
    )
    await message.answer(help_text)


# === ОБРАБОТЧИКИ КНОПОК ===

@router.message(lambda message: message.text == "📋 Мои задачи")
async def my_tasks_button(message: types.Message):
    from handlers.task import my_tasks
    await my_tasks(message)


@router.message(lambda message: message.text == "➕ Новая задача")
async def new_task_button(message: types.Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        if user.role not in ["owner", "general_director", "foreman", "pto"]:
            await message.answer("❌ У вас нет прав для создания задач.")
            return
    
    # Запускаем FSM создание задачи через команду
    await message.answer(
        "➕ Создание новой задачи\n\n"
        "Используйте команду:\n"
        "/new_task — Начать создание задачи"
    )


@router.message(lambda message: message.text == "📊 Отчёт")
async def report_button(message: types.Message):
    await message.answer(
        "📊 Для генерации отчёта используйте команду:\n"
        "/gen_report — Полный отчёт\n"
        "/monthly_report — Месячный отчёт"
    )


@router.message(lambda message: message.text == "📦 Материалы")
async def materials_button(message: types.Message):
    await message.answer(
        "📦 Управление материалами\n\n"
        "/stock — Остатки по объектам\n"
        "/add_material — Добавить материал\n"
        "/use_material — Списать материал\n"
        "/critical — Критические остатки\n"
        "/new_order — Заявка на материалы"
    )


@router.message(lambda message: message.text == "🔧 Инструменты")
async def tools_button(message: types.Message):
    await message.answer(
        "🔧 Управление инструментами\n\n"
        "/assign_tool — Закрепить инструмент\n"
        "/transfer_tool — Передать инструмент\n"
        "/return_tool — Вернуть инструмент\n"
        "/my_tools — Мои инструменты"
    )


@router.message(lambda message: message.text == "👥 Управление командой")
async def team_management(message: types.Message):
    await message.answer(
        "👥 *Управление командой*\n\n"
        "/add_user — Добавить сотрудника\n"
        "/list_users — Список всех сотрудников\n"
        "/edit_user [ID] — Редактировать сотрудника\n"
        "/delete_user [ID] — Удалить сотрудника",
        parse_mode="Markdown"
    )


@router.message(lambda message: message.text == "👥 Команда")
async def team_button(message: types.Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        if user.role == "foreman":
            result = await session.execute(
                select(User).where(User.role.in_(["worker", "electrician"]))
            )
            users = result.scalars().all()
            text = "👥 Ваша команда:\n\n"
            for u in users:
                text += f"• {u.full_name} — {u.role}\n"
            await message.answer(text)
        else:
            await message.answer("👥 Управление командой:\n/add_user — Добавить сотрудника")


@router.message(lambda message: message.text == "🔑 Веб-панель")
async def web_panel_button(message: types.Message):
    await message.answer(
        "🔑 Веб-панель доступна по адресу:\n\n"
        "http://localhost:8002/login\n\n"
        "Или используйте команду:\n"
        "/web_login"
    )


@router.message(lambda message: message.text == "👤 Мой профиль")
async def profile_button(message: types.Message):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            await message.answer(
                f"👤 Ваш профиль\n\n"
                f"📛 Имя: {user.full_name}\n"
                f"🎭 Роль: {user.role}\n"
                f"🆔 ID: {user.telegram_id}\n"
                f"📍 Объект: {user.object_id or 'Не назначен'}\n"
                f"📅 Дата: {user.created_at.strftime('%d.%m.%Y %H:%M') if user.created_at else '—'}"
            )
        else:
            await message.answer(
                "👤 Вы не зарегистрированы.\n"
                "Обратитесь к владельцу для получения доступа."
            )