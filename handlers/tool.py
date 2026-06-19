from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import Tool, ToolStatus, ToolHistory, User, UserRole
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()


class ToolAssignment(StatesGroup):
    waiting_for_tool_name = State()
    waiting_for_inventory = State()
    waiting_for_user_id = State()


# === /assign_tool — закрепление инструмента ===
@router.message(Command("assign_tool"))
async def cmd_assign_tool(message: types.Message, state: FSMContext):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для закрепления инструментов.")
            return
        
        await state.set_state(ToolAssignment.waiting_for_tool_name)
        await message.answer("🔧 Введите название инструмента:")


@router.message(ToolAssignment.waiting_for_tool_name)
async def process_tool_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ToolAssignment.waiting_for_inventory)
    await message.answer("Введите инвентарный номер инструмента:")


@router.message(ToolAssignment.waiting_for_inventory)
async def process_tool_inventory(message: types.Message, state: FSMContext):
    await state.update_data(inventory_number=message.text)
    
    async for session in get_db():
        users = await session.execute(
            select(User).where(User.role.in_([UserRole.WORKER, UserRole.ELECTRICIAN]))
        )
        users = users.scalars().all()
        
        if not users:
            await message.answer("❌ Нет доступных сотрудников для закрепления инструмента.")
            await state.clear()
            return
        
        text = "👷 Выберите сотрудника (введите Telegram ID):\n\n"
        for u in users:
            text += f"• {u.telegram_id}: {u.full_name} — {u.role.value if hasattr(u.role, 'value') else u.role}\n"
        
        await state.set_state(ToolAssignment.waiting_for_user_id)
        await message.answer(text)


@router.message(ToolAssignment.waiting_for_user_id)
async def process_tool_user(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        data = await state.get_data()
        
        async for session in get_db():
            # Проверяем, что сотрудник существует
            worker = await session.execute(
                select(User).where(User.telegram_id == user_id)
            )
            if not worker.scalar_one_or_none():
                await message.answer("❌ Сотрудник с таким ID не найден.")
                return
            
            # Проверяем уникальность инвентарного номера
            existing = await session.execute(
                select(Tool).where(Tool.inventory_number == data['inventory_number'])
            )
            if existing.scalar_one_or_none():
                await message.answer(f"❌ Инструмент с инвентарным номером {data['inventory_number']} уже существует.")
                await state.clear()
                return
            
            tool = Tool(
                name=data['name'],
                inventory_number=data['inventory_number'],
                assigned_to=user_id,
                status=ToolStatus.ASSIGNED
            )
            session.add(tool)
            
            # Создаём запись в истории
            history = ToolHistory(
                tool_id=tool.id,
                to_user=user_id
            )
            session.add(history)
            await session.commit()
            
            await message.answer(
                f"✅ Инструмент закреплён!\n\n"
                f"🔧 Название: {tool.name}\n"
                f"🔢 Инв. номер: {tool.inventory_number}\n"
                f"👷 Закреплён за: {user_id}"
            )
            await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректный ID (число)")


# === /transfer_tool — передача инструмента ===
@router.message(Command("transfer_tool"))
async def cmd_transfer_tool(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: /transfer_tool [инв. номер] [Telegram ID нового владельца]")
        return
    
    inventory = args[1]
    try:
        new_user_id = int(args[2])
    except ValueError:
        await message.answer("❌ ID пользователя должен быть числом")
        return
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для передачи инструментов.")
            return
        
        tool = await session.execute(
            select(Tool).where(Tool.inventory_number == inventory)
        )
        tool = tool.scalar_one_or_none()
        
        if not tool:
            await message.answer(f"❌ Инструмент с номером {inventory} не найден.")
            return
        
        if tool.status != ToolStatus.ASSIGNED:
            await message.answer(f"❌ Инструмент не закреплён. Статус: {tool.status.value if hasattr(tool.status, 'value') else tool.status}")
            return
        
        # Проверяем нового владельца
        new_user = await session.execute(
            select(User).where(User.telegram_id == new_user_id)
        )
        if not new_user.scalar_one_or_none():
            await message.answer("❌ Пользователь с таким ID не найден.")
            return
        
        old_user_id = tool.assigned_to
        tool.assigned_to = new_user_id
        
        # Запись в истории
        history = ToolHistory(
            tool_id=tool.id,
            from_user=old_user_id,
            to_user=new_user_id
        )
        session.add(history)
        await session.commit()
        
        await message.answer(
            f"✅ Инструмент передан!\n\n"
            f"🔧 {tool.name} ({tool.inventory_number})\n"
            f"👤 Был: {old_user_id}\n"
            f"👤 Стал: {new_user_id}"
        )


# === /return_tool — возврат инструмента ===
@router.message(Command("return_tool"))
async def cmd_return_tool(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /return_tool [инвентарный номер]")
        return
    
    inventory = args[1]
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для возврата инструментов.")
            return
        
        tool = await session.execute(
            select(Tool).where(Tool.inventory_number == inventory)
        )
        tool = tool.scalar_one_or_none()
        
        if not tool:
            await message.answer(f"❌ Инструмент с номером {inventory} не найден.")
            return
        
        old_user_id = tool.assigned_to
        tool.assigned_to = None
        tool.status = ToolStatus.AVAILABLE
        
        history = ToolHistory(
            tool_id=tool.id,
            from_user=old_user_id,
            to_user=message.from_user.id
        )
        session.add(history)
        await session.commit()
        
        await message.answer(
            f"✅ Инструмент возвращён!\n\n"
            f"🔧 {tool.name} ({tool.inventory_number})\n"
            f"📊 Статус: Доступен"
        )


# === /my_tools — мои инструменты ===
@router.message(Command("my_tools"))
async def cmd_my_tools(message: types.Message):
    async for session in get_db():
        tools = await session.execute(
            select(Tool).where(Tool.assigned_to == message.from_user.id)
        )
        tools = tools.scalars().all()
        
        if not tools:
            await message.answer("🔧 У вас нет закреплённых инструментов.")
            return
        
        text = "🔧 Мои инструменты:\n\n"
        for tool in tools:
            status_str = tool.status.value if hasattr(tool.status, 'value') else tool.status
            text += f"• {tool.name}\n"
            text += f"  Инв. номер: {tool.inventory_number}\n"
            text += f"  Статус: {status_str}\n\n"
        
        await message.answer(text)