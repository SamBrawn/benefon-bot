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


# === FSM для добавления пользователя ===
class UserRegistration(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_full_name = State()
    waiting_for_role = State()


# === FSM для добавления объекта ===
class ObjectCreation(StatesGroup):
    waiting_for_name = State()
    waiting_for_address = State()


# === /add_user — добавление пользователя (только владелец) ===
@router.message(Command("add_user"))
async def cmd_add_user(message: types.Message, state: FSMContext):
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


# === /add_object — добавление объекта (только владелец) ===
@router.message(Command("add_object"))
async def cmd_add_object(message: types.Message, state: FSMContext):
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


# === /owner_approve — утверждение заявки владельцем ===
@router.message(Command("owner_approve"))
async def cmd_owner_approve(message: types.Message):
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


# === /full_report — расширенный отчёт (для владельца) ===
@router.message(Command("full_report"))
async def cmd_full_report(message: types.Message):
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


# === /gen_report — отчёт (для гендира) ===
@router.message(Command("gen_report"))
async def cmd_gen_report(message: types.Message):
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