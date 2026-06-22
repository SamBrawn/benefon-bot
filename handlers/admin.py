from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import User, UserRole, ConstructionObject, Task, TaskStatus, SalaryLog, MaterialOrder, MaterialOrderStatus
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()

# Словари для отображения ролей на русском языке
ROLE_NAMES = {
    "owner": "Владелец",
    "general_director": "Генеральный директор",
    "pto": "Инженер ПТО",
    "foreman": "Прораб",
    "electrician": "Электрик",
    "worker": "Рабочий"
}

ROLE_EMOJI = {
    "owner": "👑",
    "general_director": "💼",
    "pto": "📐",
    "foreman": "👷",
    "electrician": "⚡",
    "worker": "🔨"
}


# === FSM для добавления пользователя ===
class UserRegistration(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_full_name = State()
    waiting_for_role = State()


# === FSM для добавления объекта ===
class ObjectCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()


# === FSM для редактирования пользователя ===
class EditUserStates(StatesGroup):
    waiting_for_new_name = State()
    waiting_for_new_role = State()
    waiting_for_new_object = State()


# === /adduser — добавление пользователя (только владелец) ===
@router.message(Command("adduser"))
async def cmd_add_user(message: types.Message, state: FSMContext):
    await state.clear()
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может добавлять пользователей.")
            return
        
        await state.set_state(UserRegistration.waiting_for_telegram_id)
        await message.answer(
            "👤 Добавление нового пользователя\n\n"
            "Введите Telegram ID пользователя:\n"
            "(Можно узнать у @userinfobot)"
        )


@router.message(UserRegistration.waiting_for_telegram_id)
async def process_telegram_id(message: types.Message, state: FSMContext):
    try:
        telegram_id = int(message.text)
        await state.update_data(telegram_id=telegram_id)
        await state.set_state(UserRegistration.waiting_for_full_name)
        await message.answer("Введите полное имя пользователя:")
    except ValueError:
        await message.answer("❌ Введите корректный ID (число)")


@router.message(UserRegistration.waiting_for_full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await state.set_state(UserRegistration.waiting_for_role)
    await message.answer(
        "Выберите роль пользователя:\n\n"
        "1 — Генеральный директор\n"
        "2 — Инженер ПТО\n"
        "3 — Прораб\n"
        "4 — Электрик\n"
        "5 — Рабочий\n"
        "6 — Владелец\n\n"
        "Введите номер роли:"
    )


@router.message(UserRegistration.waiting_for_role)
async def process_role(message: types.Message, state: FSMContext):
    role_map = {
        "1": UserRole.GENERAL_DIRECTOR,
        "2": UserRole.PTO,
        "3": UserRole.FOREMAN,
        "4": UserRole.ELECTRICIAN,
        "5": UserRole.WORKER,
        "6": UserRole.OWNER
    }
    
    if message.text not in role_map:
        await message.answer("❌ Введите номер от 1 до 6")
        return
    
    data = await state.get_data()
    role = role_map[message.text]
    
    async for session in get_db():
        existing = await session.execute(
            select(User).where(User.telegram_id == data['telegram_id'])
        )
        if existing.scalar_one_or_none():
            await message.answer(f"❌ Пользователь с ID {data['telegram_id']} уже существует.")
            await state.clear()
            return
        
        user = User(
            telegram_id=data['telegram_id'],
            full_name=data['full_name'],
            role=role
        )
        session.add(user)
        await session.commit()
        
        await message.answer(
            f"✅ Пользователь добавлен!\n\n"
            f"🆔 ID: {user.telegram_id}\n"
            f"📛 Имя: {user.full_name}\n"
            f"🎭 Роль: {user.role.value if hasattr(user.role, 'value') else user.role}"
        )
        await state.clear()


# === /addobject — добавление объекта (только владелец) ===
@router.message(Command("addobject"))
async def cmd_add_object(message: types.Message, state: FSMContext):
    await state.clear()
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может добавлять объекты.")
            return
        
        await state.set_state(ObjectCreation.waiting_for_name)
        await message.answer(
            "🏗️ Добавление нового объекта\n\n"
            "Введите название объекта:"
        )


@router.message(ObjectCreation.waiting_for_name)
async def process_object_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ObjectCreation.waiting_for_address)
    await message.answer("Введите адрес объекта (или '-' чтобы пропустить):")


@router.message(ObjectCreation.waiting_for_address)
async def process_object_address(message: types.Message, state: FSMContext):
    address = message.text if message.text != "-" else None
    data = await state.get_data()
    
    async for session in get_db():
        obj = ConstructionObject(
            name=data['name'],
            address=address
        )
        session.add(obj)
        await session.commit()
        
        await message.answer(
            f"✅ Объект добавлен!\n\n"
            f"🏗️ Название: {obj.name}\n"
            f"📍 Адрес: {obj.address or '—'}\n"
            f"🆔 ID: {obj.id}"
        )
        await state.clear()


# === /ownerapprove — утверждение заявки владельцем ===
@router.message(Command("ownerapprove"))
async def cmd_owner_approve(message: types.Message, state: FSMContext):
    await state.clear()
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /owner_approve [ID заявки]")
        return
    
    try:
        order_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID заявки должен быть числом")
        return
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может утверждать заявки.")
            return
        
        order = await session.get(MaterialOrder, order_id)
        if not order:
            await message.answer(f"❌ Заявка #{order_id} не найдена.")
            return
        
        if order.status != MaterialOrderStatus.PENDING_OWNER:
            await message.answer(f"❌ Заявка #{order_id} не ожидает утверждения владельцем.")
            return
        
        order.status = MaterialOrderStatus.APPROVED
        order.owner_approved_at = datetime.utcnow()
        await session.commit()
        
        await message.answer(f"✅ Заявка #{order_id} утверждена владельцем!")


# === /fullreport — расширенный отчёт (для владельца) ===
@router.message(Command("fullreport"))
async def cmd_full_report(message: types.Message, state: FSMContext):
    await state.clear()
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может формировать расширенный отчёт.")
            return
        
        total_tasks = len((await session.execute(select(Task))).scalars().all())
        completed = len((await session.execute(
            select(Task).where(Task.status == TaskStatus.PAID_BY_DIRECTOR)
        )).scalars().all())
        in_progress = len((await session.execute(
            select(Task).where(Task.status == TaskStatus.IN_PROGRESS)
        )).scalars().all())
        total_users = len((await session.execute(select(User))).scalars().all())
        total_objects = len((await session.execute(select(ConstructionObject))).scalars().all())
        
        total_paid = sum(s.amount for s in (await session.execute(select(SalaryLog))).scalars().all())
        
        await message.answer(
            f"📊 Расширенный отчёт\n\n"
            f"📋 Задачи:\n"
            f"  Всего: {total_tasks}\n"
            f"  В работе: {in_progress}\n"
            f"  Завершено: {completed}\n\n"
            f"👥 Пользователи: {total_users}\n"
            f"🏗️ Объекты: {total_objects}\n"
            f"💰 Всего выплачено: {total_paid} руб."
        )


# === /genreport — отчёт (для гендира) ===
@router.message(Command("genreport"))
async def cmd_gen_report(message: types.Message, state: FSMContext):
    await state.clear()
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]:
            await message.answer("❌ У вас нет прав для формирования отчёта.")
            return
        
        total_tasks = len((await session.execute(select(Task))).scalars().all())
        completed = len((await session.execute(
            select(Task).where(Task.status == TaskStatus.PAID_BY_DIRECTOR)
        )).scalars().all())
        in_progress = len((await session.execute(
            select(Task).where(Task.status == TaskStatus.IN_PROGRESS)
        )).scalars().all())
        
        total_paid = sum(s.amount for s in (await session.execute(select(SalaryLog))).scalars().all())
        
        await message.answer(
            f"📊 Отчёт по задачам\n\n"
            f"📋 Всего задач: {total_tasks}\n"
            f"🔄 В работе: {in_progress}\n"
            f"✅ Завершено: {completed}\n"
            f"💰 Выплачено: {total_paid} руб."
        )


# ========== ПРОСМОТР СОТРУДНИКОВ ==========
@router.message(Command("listusers"))
async def list_users(message: types.Message, state: FSMContext):
    await state.clear()
    """Показывает список всех зарегистрированных сотрудников."""
    async for session in get_db():
        current_user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        current_user = current_user.scalar_one_or_none()
        if not current_user or current_user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может просматривать список сотрудников.")
            return

        result = await session.execute(select(User).order_by(User.role, User.full_name))
        users = result.scalars().all()

        if not users:
            await message.answer("📋 В системе пока нет зарегистрированных сотрудников.")
            return

        text = "👥 *Список сотрудников:*\n\n"
        for user in users:
            role_key = user.role.value if hasattr(user.role, 'value') else user.role
            emoji = ROLE_EMOJI.get(role_key, "❓")
            role_display = ROLE_NAMES.get(role_key, role_key)
            text += f"{emoji} *{user.full_name}*\n"
            text += f"   🆔 ID: `{user.telegram_id}`\n"
            text += f"   🎭 Роль: {role_display}\n"
            if user.object_id:
                text += f"   🏗️ Объект: {user.object_id}\n"
            text += "\n"

        await message.answer(text, parse_mode="Markdown")


# ========== РЕДАКТИРОВАНИЕ СОТРУДНИКА ==========
@router.message(Command("edituser"))
async def edit_user_start(message: types.Message, state: FSMContext):
    await state.clear()
    """Начинает процесс редактирования сотрудника."""
    async for session in get_db():
        current_user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        current_user = current_user.scalar_one_or_none()
        if not current_user or current_user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может редактировать сотрудников.")
            return

        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Укажите ID сотрудника.\n"
                "Пример: `/edituser 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            user_id = int(parts[1])
        except ValueError:
            await message.answer("❌ ID должен быть числом.")
            return

        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer(f"❌ Пользователь с ID `{user_id}` не найден.", parse_mode="Markdown")
            return

        await state.update_data(edit_user_id=user_id)

        await state.set_state(EditUserStates.waiting_for_new_name)
        role_display = ROLE_NAMES.get(user.role.value if hasattr(user.role, 'value') else user.role, user.role)
        await message.answer(
            f"✏️ *Редактирование сотрудника*\n\n"
            f"📛 Текущее имя: {user.full_name}\n"
            f"🎭 Текущая роль: {role_display}\n"
            f"🏗️ Текущий объект: {user.object_id or 'Не назначен'}\n\n"
            f"Введите **новое имя** (или отправьте `.` чтобы оставить без изменений):",
            parse_mode="Markdown"
        )


@router.message(EditUserStates.waiting_for_new_name)
async def process_edit_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('edit_user_id')

    if message.text != ".":
        await state.update_data(new_name=message.text)

    await state.set_state(EditUserStates.waiting_for_new_role)
    await message.answer(
        "Выберите **новую роль** (или отправьте `.` чтобы оставить без изменений):\n\n"
        "1 - Генеральный директор\n"
        "2 - Инженер ПТО\n"
        "3 - Прораб\n"
        "4 - Электрик\n"
        "5 - Рабочий\n"
        "6 - Владелец\n\n"
        "Введите номер роли:",
        parse_mode="Markdown"
    )


@router.message(EditUserStates.waiting_for_new_role)
async def process_edit_role(message: types.Message, state: FSMContext):
    if message.text != ".":
        role_map = {
            "1": UserRole.GENERAL_DIRECTOR,
            "2": UserRole.PTO,
            "3": UserRole.FOREMAN,
            "4": UserRole.ELECTRICIAN,
            "5": UserRole.WORKER,
            "6": UserRole.OWNER
        }
        if message.text not in role_map:
            await message.answer("❌ Введите номер от 1 до 6")
            return
        await state.update_data(new_role=role_map[message.text])

    await state.set_state(EditUserStates.waiting_for_new_object)
    await message.answer(
        "Введите **новый ID объекта** (или отправьте `.` чтобы оставить без изменений, `0` чтобы убрать):",
        parse_mode="Markdown"
    )


@router.message(EditUserStates.waiting_for_new_object)
async def process_edit_object(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get('edit_user_id')

    try:
        if message.text == ".":
            new_object = None
        elif message.text == "0":
            new_object = None
        else:
            new_object = int(message.text)
    except ValueError:
        await message.answer("❌ ID объекта должен быть числом, `.` или `0`.")
        return

    await state.update_data(new_object=new_object)

    async for session in get_db():
        user = await session.get(User, user_id)
        if not user:
            await message.answer(f"❌ Пользователь с ID `{user_id}` не найден.", parse_mode="Markdown")
            await state.clear()
            return

        if 'new_name' in data and data['new_name'] != '.':
            user.full_name = data['new_name']
        if 'new_role' in data and data['new_role'] != '.':
            user.role = data['new_role']
        if new_object is not None:
            user.object_id = new_object if new_object != 0 else None

        await session.commit()

        await message.answer(
            f"✅ *Данные сотрудника обновлены!*\n\n"
            f"📛 Имя: {user.full_name}\n"
            f"🎭 Роль: {user.role.value if hasattr(user.role, 'value') else user.role}\n"
            f"🏗️ Объект: {user.object_id or 'Не назначен'}",
            parse_mode="Markdown"
        )
        await state.clear()


# ========== УДАЛЕНИЕ СОТРУДНИКА ==========
@router.message(Command("deleteuser"))
async def delete_user(message: types.Message, state: FSMContext):
    await state.clear()
    """Удаляет сотрудника из системы."""
    async for session in get_db():
        current_user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        current_user = current_user.scalar_one_or_none()
        if not current_user or current_user.role != UserRole.OWNER:
            await message.answer("❌ Только владелец может удалять сотрудников.")
            return

        parts = message.text.split()
        if len(parts) < 2:
            await message.answer(
                "❌ Укажите ID сотрудника.\n"
                "Пример: `/deleteuser 123456789`",
                parse_mode="Markdown"
            )
            return

        try:
            user_id = int(parts[1])
        except ValueError:
            await message.answer("❌ ID должен быть числом.")
            return

        result = await session.execute(
            select(User).where(User.telegram_id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer(f"❌ Пользователь с ID `{user_id}` не найден.", parse_mode="Markdown")
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_delete_{user_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_delete")
            ]
        ])

        role_display = ROLE_NAMES.get(user.role.value if hasattr(user.role, 'value') else user.role, user.role)
        await message.answer(
            f"⚠️ *Подтверждение удаления*\n\n"
            f"Вы уверены, что хотите удалить сотрудника?\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: `{user.telegram_id}`\n"
            f"🎭 Роль: {role_display}\n\n"
            f"Это действие **необратимо**!",
            parse_mode="Markdown",
            reply_markup=keyboard
        )


@router.callback_query(lambda c: c.data and c.data.startswith("confirm_delete_"))
async def confirm_delete_user(callback: types.CallbackQuery):
    """Подтверждение удаления сотрудника."""
    user_id = int(callback.data.split("_")[2])

    async for session in get_db():
        user = await session.get(User, user_id)
        if not user:
            await callback.message.edit_text(f"❌ Пользователь с ID `{user_id}` не найден.")
            await callback.answer()
            return

        await session.delete(user)
        await session.commit()

        await callback.message.edit_text(
            f"✅ Сотрудник удалён!\n\n"
            f"📛 Имя: {user.full_name}\n"
            f"🆔 ID: `{user.telegram_id}`",
            parse_mode="Markdown"
        )
        await callback.answer()


@router.callback_query(lambda c: c.data == "cancel_delete")
async def cancel_delete_user(callback: types.CallbackQuery):
    """Отмена удаления сотрудника."""
    await callback.message.edit_text("❌ Удаление отменено.")
    await callback.answer()
