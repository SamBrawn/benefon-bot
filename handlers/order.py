from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import MaterialOrder, MaterialOrderStatus, ConstructionObject, User, UserRole
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()


class OrderCreation(StatesGroup):
    waiting_for_object = State()
    waiting_for_materials = State()


# === /new_order — создание заявки на материалы ===
@router.message(Command("new_order"))
async def cmd_new_order(message: types.Message, state: FSMContext):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для создания заявок.")
            return
        
        objects = await session.execute(select(ConstructionObject))
        objects = objects.scalars().all()
        
        if not objects:
            await message.answer("❌ Нет доступных объектов. Сначала создайте объект через /add_object")
            return
        
        text = "🏗️ Выберите объект (введите ID):\n\n"
        for obj in objects:
            text += f"• {obj.id}: {obj.name} — {obj.address or 'адрес не указан'}\n"
        
        await state.set_state(OrderCreation.waiting_for_object)
        await message.answer(text)


@router.message(OrderCreation.waiting_for_object)
async def process_order_object(message: types.Message, state: FSMContext):
    try:
        object_id = int(message.text)
        await state.update_data(object_id=object_id)
        await state.set_state(OrderCreation.waiting_for_materials)
        await message.answer(
            "📦 Введите список материалов в формате:\n\n"
            "Название1: количество1\n"
            "Название2: количество2\n\n"
            "Пример:\n"
            "Кабель ВВГ: 100\n"
            "Розетка: 50\n"
            "Автомат: 10"
        )
    except ValueError:
        await message.answer("❌ Введите корректный ID объекта (число)")


@router.message(OrderCreation.waiting_for_materials)
async def process_order_materials(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Парсим материалы из сообщения
    lines = message.text.strip().split('\n')
    materials_list = []
    
    for line in lines:
        if ':' in line:
            parts = line.split(':')
            name = parts[0].strip()
            try:
                quantity = float(parts[1].strip().replace(',', '.'))
                materials_list.append({
                    "name": name,
                    "quantity": quantity,
                    "unit": "шт"
                })
            except ValueError:
                await message.answer(f"❌ Неверный формат количества в строке: {line}")
                return
    
    if not materials_list:
        await message.answer("❌ Не удалось распознать материалы. Используйте формат:\nНазвание: количество")
        return
    
    async for session in get_db():
        order = MaterialOrder(
            object_id=data['object_id'],
            materials_json=materials_list,
            status=MaterialOrderStatus.PENDING_PTO,
            created_by=message.from_user.id
        )
        session.add(order)
        await session.commit()
        
        text = f"✅ Заявка #{order.id} создана!\n\n"
        text += f"🏗️ Объект: {data['object_id']}\n"
        text += f"📦 Материалы:\n"
        for m in materials_list:
            text += f"  • {m['name']}: {m['quantity']} {m['unit']}\n"
        text += f"\n📌 Статус: Ожидает утверждения ПТО"
        
        await message.answer(text)
        await state.clear()


# === /web_login — вход в веб-панель ===
@router.message(Command("web_login"))
async def cmd_web_login(message: types.Message):
    from models import WebToken
    import uuid
    from datetime import timedelta
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        # Создаём токен для входа
        token = WebToken(
            user_id=user.telegram_id,
            token=str(uuid.uuid4()),
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        session.add(token)
        await session.commit()
        
        await message.answer(
            f"🔑 Веб-панель\n\n"
            f"Ссылка для входа:\n"
            f"http://localhost:8002/login?token={token.token}\n\n"
            f"⏱ Токен действителен 1 час"
        )