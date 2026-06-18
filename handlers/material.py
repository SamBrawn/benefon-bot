from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, Material, ConstructionObject, MaterialUnit
from keyboards import get_main_menu_keyboard, get_objects_keyboard, get_cancel_keyboard
import logging

logger = logging.getLogger(__name__)
router = Router()


class MaterialStates(StatesGroup):
    waiting_for_object = State()
    waiting_for_name = State()
    waiting_for_unit = State()
    waiting_for_quantity = State()


@router.message(F.text == "📦 Материалы")
async def cmd_materials(message: Message):
    """Просмотр материалов"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы")
            return

        # Получаем объекты пользователя
        if user.role == UserRole.OWNER:
            result = await session.execute(select(ConstructionObject))
            objects = result.scalars().all()
        else:
            result = await session.execute(
                select(ConstructionObject).where(ConstructionObject.id == user.object_id)
            )
            objects = result.scalars().all()

        if not objects:
            await message.answer("❌ Нет доступных объектов")
            return

        await message.answer(
            "Выберите объект для просмотра материалов:",
            reply_markup=get_objects_keyboard(objects)
        )


@router.callback_query(F.data.startswith("object_"))
async def callback_show_materials(callback: CallbackQuery, session: AsyncSession):
    """Показать материалы объекта"""
    object_id = int(callback.data.split("_")[1])

    from sqlalchemy import select
    result = await session.execute(
        select(Material).where(Material.object_id == object_id)
    )
    materials = result.scalars().all()

    if not materials:
        await callback.message.answer("📦 На этом объекте пока нет материалов")
        await callback.answer()
        return

    materials_text = f"📦 Материалы на объекте:\n\n"
    for material in materials:
        critical = ""
        if material.quantity <= (material.critical_percent or 10) * material.initial_quantity / 100:
            critical = "⚠️ КРИТИЧЕСКИЙ ОСТАТОК!\n"

        materials_text += f"📌 {material.name}\n"
        materials_text += f"   Остаток: {material.quantity} {material.unit.value}\n"
        materials_text += f"   Начальное: {material.initial_quantity} {material.unit.value}\n"
        materials_text += critical + "\n"

    await callback.message.answer(materials_text)
    await callback.answer()


@router.message(F.text == "➕ Добавить материал")
async def cmd_add_material(message: Message, state: FSMContext):
    """Добавление материала"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO]:
            await message.answer("❌ У вас нет прав для добавления материалов")
            return

        # Получаем объекты
        if user.role == UserRole.OWNER:
            result = await session.execute(select(ConstructionObject))
            objects = result.scalars().all()
        else:
            result = await session.execute(
                select(ConstructionObject).where(ConstructionObject.id == user.object_id)
            )
            objects = result.scalars().all()

        if not objects:
            await message.answer("❌ Нет доступных объектов")
            return

        await message.answer(
            "Выберите объект:",
            reply_markup=get_objects_keyboard(objects)
        )
        await state.set_state(MaterialStates.waiting_for_object)


@router.callback_query(MaterialStates.waiting_for_object, F.data.startswith("object_"))
async def process_material_object(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора объекта"""
    object_id = int(callback.data.split("_")[1])
    await state.update_data(object_id=object_id)

    await callback.message.answer(
        "✅ Объект выбран.\n\n"
        "Введите название материала:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(MaterialStates.waiting_for_name)
    await callback.answer()


@router.message(MaterialStates.waiting_for_name)
async def process_material_name(message: Message, state: FSMContext):
    """Обработка названия материала"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление материала отменено", reply_markup=get_main_menu_keyboard(UserRole.PTO))
        return

    await state.update_data(name=message.text)
    await message.answer(
        "✅ Название сохранено.\n\n"
        "Выберите единицу измерения:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(MaterialStates.waiting_for_unit)


@router.message(MaterialStates.waiting_for_unit)
async def process_material_unit(message: Message, state: FSMContext):
    """Обработка единицы измерения"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление материала отменено", reply_markup=get_main_menu_keyboard(UserRole.PTO))
        return

    unit_map = {
        "шт": MaterialUnit.PIECE,
        "м": MaterialUnit.METER,
        "м²": MaterialUnit.SQUARE_METER,
        "л": MaterialUnit.LITER,
        "кг": MaterialUnit.KILOGRAM,
        "уп": MaterialUnit.PACK,
    }

    unit = unit_map.get(message.text)
    if not unit:
        await message.answer("❌ Неверная единица. Используйте: шт, м, м², л, кг, уп")
        return

    await state.update_data(unit=unit)
    await message.answer(
        "✅ Единица измерения сохранена.\n\n"
        "Введите начальное количество:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(MaterialStates.waiting_for_quantity)


@router.message(MaterialStates.waiting_for_quantity)
async def process_material_quantity(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка количества и создание материала"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Добавление материала отменено", reply_markup=get_main_menu_keyboard(UserRole.PTO))
        return

    try:
        quantity = float(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число")
        return

    data = await state.get_data()

    # Создаём материал
    material = Material(
        object_id=data["object_id"],
        name=data["name"],
        unit=data["unit"],
        quantity=quantity,
        initial_quantity=quantity
    )

    session.add(material)
    await session.commit()

    await message.answer(
        f"✅ Материал добавлен!\n\n"
        f"📌 {data['name']}\n"
        f"📦 {quantity} {data['unit'].value}",
        reply_markup=get_main_menu_keyboard(UserRole.PTO)
    )

    await state.clear()