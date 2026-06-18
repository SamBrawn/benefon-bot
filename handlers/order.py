from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, MaterialOrder, MaterialOrderStatus, ConstructionObject
from keyboards import get_main_menu_keyboard, get_objects_keyboard, get_orders_keyboard, get_cancel_keyboard
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)
router = Router()


class OrderStates(StatesGroup):
    waiting_for_object = State()
    waiting_for_materials = State()


@router.message(F.text == "📝 Заявка на материалы")
async def cmd_new_order(message: Message, state: FSMContext):
    """Создание заявки на материалы"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role != UserRole.FOREMAN:
            await message.answer("❌ Только прораб может создавать заявки")
            return

        # Получаем объекты
        result = await session.execute(
            select(ConstructionObject).where(ConstructionObject.id == user.object_id)
        )
        objects = result.scalars().all()

        if not objects:
            await message.answer("❌ Нет доступных объектов")
            return

        await message.answer(
            "Выберите объект для заявки:",
            reply_markup=get_objects_keyboard(objects)
        )
        await state.set_state(OrderStates.waiting_for_object)


@router.callback_query(OrderStates.waiting_for_object, F.data.startswith("object_"))
async def process_order_object(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора объекта"""
    object_id = int(callback.data.split("_")[1])
    await state.update_data(object_id=object_id, materials=[])

    await callback.message.answer(
        "✅ Объект выбран.\n\n"
        "Введите материалы в формате:\n"
        "Название | Количество | Единица (шт/м/м²/л/кг/уп)\n\n"
        "Пример:\n"
        "Кабель ВВГнг 3х2.5 | 100 | м\n"
        "Розетка Schneider | 20 | шт\n\n"
        "Когда закончите, отправьте 'Готово'",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(OrderStates.waiting_for_materials)
    await callback.answer()


@router.message(OrderStates.waiting_for_materials)
async def process_order_materials(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка материалов"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание заявки отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    if message.text == "Готово":
        # Создаём заявку
        data = await state.get_data()
        materials = data.get("materials", [])

        if not materials:
            await message.answer("❌ Добавьте хотя бы один материал")
            return

        order = MaterialOrder(
            object_id=data["object_id"],
            materials_json=materials,
            status=MaterialOrderStatus.PENDING_PTO,
            created_by=message.from_user.id
        )

        session.add(order)
        await session.commit()

        await message.answer(
            f"✅ Заявка #{order.id} создана!\n"
            f"Материалов: {len(materials)}\n"
            f"Статус: Ожидает ПТО",
            reply_markup=get_main_menu_keyboard(UserRole.FOREMAN)
        )

        # Уведомляем ПТО
        await notify_pto_about_order(order.id, materials)
        await state.clear()
        return

    # Парсим материал
    try:
        parts = message.text.split("|")
        if len(parts) != 3:
            raise ValueError()

        name = parts[0].strip()
        quantity = float(parts[1].strip())
        unit = parts[2].strip()

        data = await state.get_data()
        materials = data.get("materials", [])
        materials.append({
            "name": name,
            "quantity": quantity,
            "unit": unit
        })

        await state.update_data(materials=materials)
        await message.answer(
            f"✅ Материал добавлен: {name} ({quantity} {unit})\n"
            f"Всего материалов: {len(materials)}\n\n"
            f"Отправьте ещё материал или 'Готово' для завершения"
        )

    except (ValueError, IndexError):
        await message.answer(
            "❌ Неверный формат. Используйте:\n"
            "Название | Количество | Единица\n\n"
            "Пример: Кабель | 100 | м"
        )


@router.message(F.text == "📋 Заявки")
async def cmd_orders(message: Message):
    """Просмотр заявок"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы")
            return

        # Получаем заявки
        if user.role in [UserRole.OWNER, UserRole.PTO]:
            result = await session.execute(
                select(MaterialOrder).order_by(MaterialOrder.created_at.desc())
            )
        else:
            result = await session.execute(
                select(MaterialOrder).where(MaterialOrder.created_by == user.telegram_id).order_by(MaterialOrder.created_at.desc())
            )

        orders = result.scalars().all()

        if not orders:
            await message.answer("📋 Пока нет заявок")
            return

        await message.answer(
            "📋 Список заявок:",
            reply_markup=get_orders_keyboard(orders)
        )


@router.callback_query(F.data.startswith("order_"))
async def callback_show_order(callback: CallbackQuery, session: AsyncSession):
    """Показать детали заявки"""
    order_id = int(callback.data.split("_")[1])

    from sqlalchemy import select
    result = await session.execute(
        select(MaterialOrder).where(MaterialOrder.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        await callback.answer("❌ Заявка не найдена")
        return

    status_names = {
        MaterialOrderStatus.PENDING_PTO: "⏳ Ожидает ПТО",
        MaterialOrderStatus.PENDING_OWNER: "🔍 Ожидает владельца",
        MaterialOrderStatus.APPROVED: "✅ Утверждена",
        MaterialOrderStatus.REJECTED: "❌ Отклонена"
    }

    order_text = f"📝 Заявка #{order.id}\n"
    order_text += f"📊 Статус: {status_names.get(order.status, order.status)}\n"
    order_text += f"📅 Создана: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n\n"
    order_text += "Материалы:\n"

    for material in order.materials_json:
        order_text += f"  • {material['name']}: {material['quantity']} {material['unit']}\n"

    # Кнопки действий
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []

    if order.status == MaterialOrderStatus.PENDING_PTO and callback.from_user.id in [UserRole.PTO, UserRole.OWNER]:
        buttons.append([InlineKeyboardButton(text="✅ Утвердить (ПТО)", callback_data=f"order_approve_pto_{order.id}")])
        buttons.append([InlineKeyboardButton(text="❌ Отклонить", callback_data=f"order_reject_{order.id}")])

    if order.status == MaterialOrderStatus.PENDING_OWNER and callback.from_user.id == UserRole.OWNER:
        buttons.append([InlineKeyboardButton(text="✅ Утвердить (Владелец)", callback_data=f"order_approve_owner_{order.id}")])
        buttons.append([InlineKeyboardButton(text="❌ Отклонить", callback_data=f"order_reject_{order.id}")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    await callback.message.answer(order_text, reply_markup=keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("order_approve_pto_"))
async def callback_approve_pto(callback: CallbackQuery, session: AsyncSession):
    """Утверждение ПТО"""
    order_id = int(callback.data.split("_")[3])

    from sqlalchemy import select
    result = await session.execute(
        select(MaterialOrder).where(MaterialOrder.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        await callback.answer("❌ Заявка не найдена")
        return

    order.status = MaterialOrderStatus.PENDING_OWNER
    order.pto_approved_at = datetime.utcnow()
    await session.commit()

    await callback.message.answer(f"✅ Заявка #{order_id} утверждена ПТО! Отправлена владельцу.")
    await callback.answer()


@router.callback_query(F.data.startswith("order_approve_owner_"))
async def callback_approve_owner(callback: CallbackQuery, session: AsyncSession):
    """Утверждение владельцем"""
    order_id = int(callback.data.split("_")[3])

    from sqlalchemy import select
    result = await session.execute(
        select(MaterialOrder).where(MaterialOrder.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        await callback.answer("❌ Заявка не найдена")
        return

    order.status = MaterialOrderStatus.APPROVED
    order.owner_approved_at = datetime.utcnow()
    await session.commit()

    await callback.message.answer(f"✅ Заявка #{order_id} утверждена владельцем!")
    await callback.answer()


@router.callback_query(F.data.startswith("order_reject_"))
async def callback_reject_order(callback: CallbackQuery, session: AsyncSession):
    """Отклонение заявки"""
    order_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(MaterialOrder).where(MaterialOrder.id == order_id)
    )
    order = result.scalar_one_or_none()

    if not order:
        await callback.answer("❌ Заявка не найдена")
        return

    order.status = MaterialOrderStatus.REJECTED
    await session.commit()

    await callback.message.answer(f"❌ Заявка #{order_id} отклонена")
    await callback.answer()


async def notify_pto_about_order(order_id: int, materials: list):
    """Уведомление ПТО о новой заявке"""
    # TODO: Реализовать отправку уведомления всем ПТО
    pass