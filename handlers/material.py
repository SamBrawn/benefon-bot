from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import Material, MaterialUnit, ConstructionObject, User, UserRole
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()


class MaterialAddition(StatesGroup):
    waiting_for_object = State()
    waiting_for_name = State()
    waiting_for_unit = State()
    waiting_for_quantity = State()


class MaterialUsage(StatesGroup):
    waiting_for_material_id = State()
    waiting_for_quantity = State()


# === /add_material — добавление материала ===
@router.message(Command("add_material"))
async def cmd_add_material(message: types.Message, state: FSMContext):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для добавления материалов.")
            return
        
        objects = await session.execute(select(ConstructionObject))
        objects = objects.scalars().all()
        
        if not objects:
            await message.answer("❌ Нет доступных объектов. Сначала создайте объект через /add_object")
            return
        
        text = "🏗️ Выберите объект (введите ID):\n\n"
        for obj in objects:
            text += f"• {obj.id}: {obj.name} — {obj.address or 'адрес не указан'}\n"
        
        await state.set_state(MaterialAddition.waiting_for_object)
        await message.answer(text)


@router.message(MaterialAddition.waiting_for_object)
async def process_material_object(message: types.Message, state: FSMContext):
    try:
        object_id = int(message.text)
        await state.update_data(object_id=object_id)
        await state.set_state(MaterialAddition.waiting_for_name)
        await message.answer("📦 Введите название материала:")
    except ValueError:
        await message.answer("❌ Введите корректный ID объекта (число)")


@router.message(MaterialAddition.waiting_for_name)
async def process_material_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(MaterialAddition.waiting_for_unit)
    await message.answer(
        "📏 Введите единицу измерения:\n\n"
        "1 — шт\n2 — м\n3 — м²\n4 — л\n5 — кг\n6 — уп\n\n"
        "Введите номер:"
    )


@router.message(MaterialAddition.waiting_for_unit)
async def process_material_unit(message: types.Message, state: FSMContext):
    unit_map = {
        "1": MaterialUnit.PIECE,
        "2": MaterialUnit.METER,
        "3": MaterialUnit.SQUARE_METER,
        "4": MaterialUnit.LITER,
        "5": MaterialUnit.KILOGRAM,
        "6": MaterialUnit.PACK
    }
    
    if message.text not in unit_map:
        await message.answer("❌ Введите номер от 1 до 6")
        return
    
    await state.update_data(unit=unit_map[message.text])
    await state.set_state(MaterialAddition.waiting_for_quantity)
    await message.answer("🔢 Введите количество:")


@router.message(MaterialAddition.waiting_for_quantity)
async def process_material_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = float(message.text.replace(',', '.'))
        data = await state.get_data()
        
        async for session in get_db():
            material = Material(
                object_id=data['object_id'],
                name=data['name'],
                unit=data['unit'],
                quantity=quantity,
                initial_quantity=quantity
            )
            session.add(material)
            await session.commit()
            
            unit_str = material.unit.value if hasattr(material.unit, 'value') else material.unit
            await message.answer(
                f"✅ Материал добавлен!\n\n"
                f"📦 Название: {material.name}\n"
                f"📏 Ед. изм.: {unit_str}\n"
                f"🔢 Количество: {material.quantity}\n"
                f"🏗️ Объект: {material.object_id}"
            )
            await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")


# === /use_material — списание материала ===
@router.message(Command("use_material"))
async def cmd_use_material(message: types.Message, state: FSMContext):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для списания материалов.")
            return
        
        materials = await session.execute(
            select(Material).order_by(Material.object_id, Material.name)
        )
        materials = materials.scalars().all()
        
        if not materials:
            await message.answer("📦 Нет материалов для списания.")
            return
        
        text = "📦 Выберите материал для списания (введите ID):\n\n"
        for m in materials:
            unit_str = m.unit.value if hasattr(m.unit, 'value') else m.unit
            text += f"• {m.id}: {m.name} — {m.quantity} {unit_str}\n"
        
        await state.set_state(MaterialUsage.waiting_for_material_id)
        await message.answer(text)


@router.message(MaterialUsage.waiting_for_material_id)
async def process_use_material_id(message: types.Message, state: FSMContext):
    try:
        material_id = int(message.text)
        await state.update_data(material_id=material_id)
        
        async for session in get_db():
            material = await session.get(Material, material_id)
            if not material:
                await message.answer("❌ Материал не найден.")
                await state.clear()
                return
            
            unit_str = material.unit.value if hasattr(material.unit, 'value') else material.unit
            await message.answer(
                f"📦 {material.name} — доступно {material.quantity} {unit_str}\n\n"
                "Введите количество для списания:"
            )
            await state.set_state(MaterialUsage.waiting_for_quantity)
    except ValueError:
        await message.answer("❌ Введите корректный ID (число)")


@router.message(MaterialUsage.waiting_for_quantity)
async def process_use_quantity(message: types.Message, state: FSMContext):
    try:
        quantity = float(message.text.replace(',', '.'))
        data = await state.get_data()
        
        async for session in get_db():
            material = await session.get(Material, data['material_id'])
            if not material:
                await message.answer("❌ Материал не найден.")
                await state.clear()
                return
            
            if quantity > material.quantity:
                unit_str = material.unit.value if hasattr(material.unit, 'value') else material.unit
                await message.answer(f"❌ Недостаточно материала. Доступно: {material.quantity} {unit_str}")
                return
            
            material.quantity -= quantity
            material.last_updated = datetime.utcnow()
            await session.commit()
            
            unit_str = material.unit.value if hasattr(material.unit, 'value') else material.unit
            await message.answer(
                f"✅ Материал списан!\n\n"
                f"📦 {material.name}\n"
                f"🔢 Списано: {quantity} {unit_str}\n"
                f"📊 Остаток: {material.quantity} {unit_str}"
            )
            await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число")


# === /stock — остатки материалов ===
@router.message(Command("stock"))
async def cmd_stock(message: types.Message):
    async for session in get_db():
        materials = await session.execute(
            select(Material).order_by(Material.object_id, Material.name)
        )
        materials = materials.scalars().all()
        
        if not materials:
            await message.answer("📦 Склад пуст.")
            return
        
        text = "📦 Остатки материалов:\n\n"
        current_object = None
        
        for m in materials:
            obj = await session.get(ConstructionObject, m.object_id)
            obj_name = obj.name if obj else f"Объект {m.object_id}"
            
            if current_object != obj_name:
                current_object = obj_name
                text += f"\n🏗️ {obj_name}\n"
            
            unit_str = m.unit.value if hasattr(m.unit, 'value') else m.unit
            text += f"• {m.name}: {m.quantity} {unit_str}\n"
        
        await message.answer(text)


# === /critical — критические остатки ===
@router.message(Command("critical"))
async def cmd_critical(message: types.Message):
    async for session in get_db():
        materials = await session.execute(
            select(Material).order_by(Material.object_id, Material.name)
        )
        materials = materials.scalars().all()
        
        critical_materials = []
        for m in materials:
            if m.initial_quantity > 0:
                percent = (m.quantity / m.initial_quantity) * 100
                if percent <= (m.critical_percent or 10.0):
                    critical_materials.append(m)
        
        if not critical_materials:
            await message.answer("✅ Критических остатков нет.")
            return
        
        text = "⚠️ Критические остатки:\n\n"
        for m in critical_materials:
            obj = await session.get(ConstructionObject, m.object_id)
            obj_name = obj.name if obj else f"Объект {m.object_id}"
            unit_str = m.unit.value if hasattr(m.unit, 'value') else m.unit
            percent = (m.quantity / m.initial_quantity) * 100
            text += f"• {m.name} ({obj_name}): {m.quantity} {unit_str} ({percent:.0f}%)\n"
        
        await message.answer(text)