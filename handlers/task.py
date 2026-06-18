from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, Task, TaskStatus, ConstructionObject
from keyboards import get_main_menu_keyboard, get_task_actions_keyboard, get_objects_keyboard, get_cancel_keyboard
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()


class TaskCreationStates(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_work_type = State()
    waiting_for_cost = State()
    waiting_for_deadline = State()
    waiting_for_executor = State()
    waiting_for_object = State()


@router.message(F.text == "➕ Создать задачу")
async def cmd_new_task(message: Message, state: FSMContext):
    """Начало создания задачи"""
    async for session in get_db():
        from sqlalchemy import select
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для создания задач")
            return

        await message.answer(
            "📝 Создание новой задачи\n\n"
            "Введите название задачи:",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(TaskCreationStates.waiting_for_title)


@router.message(TaskCreationStates.waiting_for_title)
async def process_task_title(message: Message, state: FSMContext):
    """Обработка названия задачи"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    await state.update_data(title=message.text)
    await message.answer(
        "✅ Название сохранено.\n\n"
        "Введите описание задачи (или '-' чтобы пропустить):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(TaskCreationStates.waiting_for_description)


@router.message(TaskCreationStates.waiting_for_description)
async def process_task_description(message: Message, state: FSMContext):
    """Обработка описания"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    description = message.text if message.text != "-" else None
    await state.update_data(description=description)
    await message.answer(
        "✅ Описание сохранено.\n\n"
        "Введите вид работ (например: Электромонтаж, Сантехника):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(TaskCreationStates.waiting_for_work_type)


@router.message(TaskCreationStates.waiting_for_work_type)
async def process_task_work_type(message: Message, state: FSMContext):
    """Обработка вида работ"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    await state.update_data(work_type=message.text)
    await message.answer(
        "✅ Вид работ сохранён.\n\n"
        "Введите стоимость (в рублях) или '-' чтобы пропустить:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(TaskCreationStates.waiting_for_cost)


@router.message(TaskCreationStates.waiting_for_cost)
async def process_task_cost(message: Message, state: FSMContext):
    """Обработка стоимости"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    cost = None
    if message.text != "-":
        try:
            cost = float(message.text)
        except ValueError:
            await message.answer("❌ Неверный формат. Введите число или '-'")
            return

    await state.update_data(cost=cost)
    await message.answer(
        "✅ Стоимость сохранена.\n\n"
        "Введите дедлайн (ДД.ММ.ГГГГ) или '-' чтобы пропустить:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(TaskCreationStates.waiting_for_deadline)


@router.message(TaskCreationStates.waiting_for_deadline)
async def process_task_deadline(message: Message, state: FSMContext):
    """Обработка дедлайна"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    deadline = None
    if message.text != "-":
        try:
            deadline = datetime.strptime(message.text, "%d.%m.%Y")
        except ValueError:
            await message.answer("❌ Неверный формат. Используйте ДД.ММ.ГГГГ или '-'")
            return

    await state.update_data(deadline=deadline)
    await message.answer(
        "✅ Дедлайн сохранён.\n\n"
        "Введите Telegram ID исполнителя:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(TaskCreationStates.waiting_for_executor)


@router.message(TaskCreationStates.waiting_for_executor)
async def process_task_executor(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка исполнителя"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("❌ Создание задачи отменено", reply_markup=get_main_menu_keyboard(UserRole.FOREMAN))
        return

    try:
        executor_id = int(message.text)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите числовой Telegram ID")
        return

    # Проверяем существование исполнителя
    from sqlalchemy import select
    result = await session.execute(
        select(User).where(User.telegram_id == executor_id)
    )
    executor = result.scalar_one_or_none()

    if not executor:
        await message.answer("❌ Пользователь с таким ID не найден")
        return

    await state.update_data(executor_id=executor_id)

    # Запрашиваем объект
    result = await session.execute(
        select(ConstructionObject).where(ConstructionObject.is_active == True)
    )
    objects = result.scalars().all()

    if not objects:
        await message.answer("❌ Нет доступных объектов")
        await state.clear()
        return

    await message.answer(
        "✅ Исполнитель выбран.\n\n"
        "Выберите объект:",
        reply_markup=get_objects_keyboard(objects)
    )
    await state.set_state(TaskCreationStates.waiting_for_object)


@router.callback_query(TaskCreationStates.waiting_for_object, F.data.startswith("object_"))
async def process_task_object(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработка выбора объекта и создание задачи"""
    object_id = int(callback.data.split("_")[1])
    data = await state.get_data()

    # Создаём задачу
    task = Task(
        title=data["title"],
        description=data.get("description"),
        work_type=data.get("work_type"),
        cost=data.get("cost"),
        deadline=data.get("deadline"),
        assigned_to=data["executor_id"],
        assigned_by=callback.from_user.id,
        object_id=object_id,
        status=TaskStatus.ASSIGNED
    )

    session.add(task)
    await session.commit()

    # Уведомляем исполнителя
    try:
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(
            data["executor_id"],
            f"📋 Вам назначена новая задача!\n\n"
            f"📌 {data['title']}\n"
            f"📝 {data.get('description', 'Без описания')}\n"
            f"🔧 {data.get('work_type', 'Не указан')}\n"
            f"💰 {data.get('cost', 0)} руб.\n"
            f"📅 {data.get('deadline', 'Без дедлайна')}"
        )
    except Exception as e:
        logger.error(f"Failed to notify executor: {e}")

    await callback.message.answer(
        f"✅ Задача создана!\n\n"
        f"📌 {data['title']}\n"
        f"👤 Исполнитель: {data['executor_id']}",
        reply_markup=get_main_menu_keyboard(UserRole.FOREMAN)
    )

    await state.clear()
    await callback.answer()


@router.message(F.text == "📋 Мои задачи")
async def cmd_my_tasks(message: Message):
    """Показать задачи пользователя"""
    async for session in get_db():
        from sqlalchemy import select
        from datetime import datetime

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы")
            return

        # Получаем задачи (назначенные или созданные)
        result = await session.execute(
            select(Task).where(
                (Task.assigned_to == user.telegram_id) |
                (Task.assigned_by == user.telegram_id)
            ).order_by(Task.created_at.desc())
        )
        tasks = result.scalars().all()

        if not tasks:
            await message.answer("📋 У вас пока нет задач")
            return

        tasks_text = "📋 Ваши задачи:\n\n"
        for task in tasks[:10]:  # Показываем последние 10
            status_emoji = {
                TaskStatus.ASSIGNED: "📌",
                TaskStatus.IN_PROGRESS: "⚙️",
                TaskStatus.UNDER_REVIEW: "🔍",
                TaskStatus.APPROVED_BY_FOREMAN: "✅",
                TaskStatus.PAID_BY_DIRECTOR: "💰"
            }.get(task.status, "📋")

            tasks_text += f"{status_emoji} #{task.id} {task.title}\n"
            tasks_text += f"   Статус: {task.status}\n\n"

        await message.answer(tasks_text)


@router.callback_query(F.data.startswith("task_start_"))
async def callback_task_start(callback: CallbackQuery, session: AsyncSession):
    """Начать выполнение задачи"""
    task_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        await callback.answer("❌ Задача не найдена")
        return

    if task.assigned_to != callback.from_user.id:
        await callback.answer("❌ Это не ваша задача")
        return

    task.status = TaskStatus.IN_PROGRESS
    await session.commit()

    await callback.message.answer(f"▶️ Задача #{task_id} начата!")
    await callback.answer("✅ Статус обновлён")


@router.callback_query(F.data.startswith("task_approve_"))
async def callback_task_approve(callback: CallbackQuery, session: AsyncSession):
    """Утвердить задачу"""
    task_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        await callback.answer("❌ Задача не найдена")
        return

    task.status = TaskStatus.APPROVED_BY_FOREMAN
    task.approved_by_foreman_at = datetime.utcnow()
    await session.commit()

    # Уведомляем исполнителя
    try:
        from aiogram import Bot
        bot = Bot(token=settings.BOT_TOKEN)
        await bot.send_message(
            task.assigned_to,
            f"✅ Ваша задача #{task_id} утверждена прорабом!"
        )
    except Exception as e:
        logger.error(f"Failed to notify worker: {e}")

    await callback.message.answer(f"✅ Задача #{task_id} утверждена!")
    await callback.answer()


@router.callback_query(F.data.startswith("task_reject_"))
async def callback_task_reject(callback: CallbackQuery, session: AsyncSession):
    """Отклонить задачу"""
    task_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        await callback.answer("❌ Задача не найдена")
        return

    task.status = TaskStatus.IN_PROGRESS  # Возвращаем в работу
    await session.commit()

    await callback.message.answer(f"❌ Задача #{task_id} отклонена, возвращена в работу")
    await callback.answer()


@router.callback_query(F.data.startswith("task_pay_"))
async def callback_task_pay(callback: CallbackQuery, session: AsyncSession):
    """Оплатить задачу"""
    task_id = int(callback.data.split("_")[2])

    from sqlalchemy import select
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if not task:
        await callback.answer("❌ Задача не найдена")
        return

    if not task.cost:
        await callback.answer("❌ У задачи не указана стоимость")
        return

    task.status = TaskStatus.PAID_BY_DIRECTOR
    task.paid_by_director_at = datetime.utcnow()
    await session.commit()

    # Создаём запись в salary_log
    from models import SalaryLog
    salary = SalaryLog(
        user_id=task.assigned_to,
        task_id=task.id,
        amount=task.cost
    )
    session.add(salary)
    await session.commit()

    await callback.message.answer(
        f"💰 Задача #{task_id} оплачена!\n"
        f"💵 Сумма: {task.cost} руб."
    )
    await callback.answer("✅ Оплата проведена")