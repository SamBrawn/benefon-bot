from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, Tool, ToolStatus, ToolHistory
from keyboards import get_main_menu_keyboard, get_tools_keyboard, get_cancel_keyboard
import logging

logger = logging.getLogger(__name__)
router = Router()


class ToolAssignmentStates(StatesGroup):
    waiting_for_tool = State()
    waiting_for_user = State()


@router.message(F.text == "🔧 Инструменты")
async def cmd_tools(message: Message):
    """Просмотр инструментов"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы")
            return

        # Получаем инструменты
        result = await session.execute(select(Tool))
        tools = result.scalars().all()

        if not tools:
            await message.answer("🔧 Пока нет инструментов")
            return

        await message.answer(
            "🔧 Список инструментов:",
            reply_markup=get_tools_keyboard(tools)
        )


@router.callback_query(F.data.startswith("tool_"))
async def callback_show_tool(callback: CallbackQuery, session: AsyncSession):
    """Показать детали инструмента"""
    tool_id = int(callback.data.split("_")[1])

    from sqlalchemy import select
    result = await session.execute(
        select(Tool).where(Tool.id == tool_id)
    )
    tool = result.scalar_one_or_none()

    if not tool:
        await callback.answer("❌ Инструмент не найден")
        return

    # Получаем историю
    result = await session.execute(
        select(ToolHistory).where(ToolHistory.tool_id == tool_id).order_by(ToolHistory.date.desc()).limit(5)
    )
    history = result.scalars().all()

    tool_text = f"🔧 {tool.name}\n"
    tool_text += f"📋 Инвентарный номер: {tool.inventory_number}\n"
    tool_text += f"📊 Статус: {get_tool_status_name(tool.status)}\n"

    if history:
        tool_text += "\n📜 Последние перемещения:\n"
        for h in history:
            tool_text += f"  {h.date.strftime('%d.%m.%Y')} — пользователь {h.to_user}\n"

    # Кнопки действий
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []

    if tool.status == ToolStatus.AVAILABLE:
        buttons.append([InlineKeyboardButton(text="👤 Назначить", callback_data=f"tool_assign_{tool.id}")])

    if tool.status == ToolStatus.ASSIGNED:
        buttons.append([InlineKeyboardButton(text="🔄 Вернуть", callback_data=f"tool_return_{tool.id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await callback.message.answer(tool_text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("tool_assign_"))
async def callback_assign_tool(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Назначение инструмента"""
    tool_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Tool).where(Tool.id == tool_id)
    )
    tool = result.scalar_one_or_none()

    if not tool or tool.status != ToolStatus.AVAILABLE:
        await callback.answer("❌ Инструмент недоступен")
        return

    await state.update_data(tool_id=tool_id)
    await callback.message.answer(
        "👤 Введите Telegram ID пользователя для назначения:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ToolAssignmentStates.waiting_for_user)
    await callback.answer()


@router.message(ToolAssignmentStates.waiting_for_user)
async def process_tool_user(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка назначения инструмента"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Назначение отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID")
        return

    from sqlalchemy import select
    result = await session.execute(
        select(User).where(User.telegram_id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user:
        await message.answer("❌ Пользователь не найден")
        return

    data = await state.get_data()
    tool_id = data.get("tool_id")

    result = await session.execute(
        select(Tool).where(Tool.id == tool_id)
    )
    tool = result.scalar_one_or_none()

    if tool:
        # Создаём историю
        history = ToolHistory(
            tool_id=tool.id,
            to_user=user.telegram_id
        )
        session.add(history)

        # Обновляем инструмент
        tool.assigned_to = user.telegram_id
        tool.status = ToolStatus.ASSIGNED
        await session.commit()

        # Уведомляем пользователя
        try:
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                user.telegram_id,
                f"🔧 Вам назначен инструмент: {tool.name}"
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")

        await message.answer(
            f"✅ Инструмент назначен!\n"
            f"🔧 {tool.name}\n"
            f"👤 {user.full_name}",
            reply_markup=get_main_menu_keyboard(UserRole.FOREMAN)
        )

    await state.clear()


@router.callback_query(F.data.startswith("tool_return_"))
async def callback_return_tool(callback: CallbackQuery, session: AsyncSession):
    """Возврат инструмента"""
    tool_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Tool).where(Tool.id == tool_id)
    )
    tool = result.scalar_one_or_none()

    if not tool or tool.status != ToolStatus.ASSIGNED:
        await callback.answer("❌ Инструмент не назначен")
        return

    # Создаём историю
    history = ToolHistory(
        tool_id=tool.id,
        from_user=tool.assigned_to,
        to_user=0  # Возврат на склад
    )
    session.add(history)

    # Обновляем инструмент
    tool.assigned_to = None
    tool.status = ToolStatus.AVAILABLE
    await session.commit()

    await callback.message.answer(
        f"✅ Инструмент возвращён на склад!\n"
        f"🔧 {tool.name}",
        reply_markup=get_main_menu_keyboard(UserRole.FOREMAN)
    )
    await callback.answer()


def get_tool_status_name(status: ToolStatus) -> str:
    """Получить название статуса"""
    names = {
        ToolStatus.AVAILABLE: "✅ Доступен",
        ToolStatus.ASSIGNED: "👤 Назначен",
        ToolStatus.IN_REPAIR: "🔧 В ремонте",
        ToolStatus.WRITTEN_OFF: "❌ Списан"
    }
    return names.get(status, status.value)