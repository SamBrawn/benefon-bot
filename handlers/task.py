from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import User, UserRole, Task, TaskStatus, ConstructionObject, SalaryLog
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = Router()


# === FSM для создания задачи ===
class TaskCreation(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_work_type = State()
    waiting_for_cost = State()
    waiting_for_deadline = State()
    waiting_for_object = State()
    waiting_for_assignee = State()


# === ПРОСТЫЕ ФУНКЦИИ ДЛЯ КНОПОК ===

async def my_tasks(message: types.Message):
    """Показать задачи пользователя (вызывается из кнопки меню)"""
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        result = await session.execute(
            select(Task).where(
                (Task.assigned_to == user.telegram_id) |
                (Task.assigned_by == user.telegram_id)
            ).order_by(Task.created_at.desc())
        )
        tasks = result.scalars().all()
        
        if not tasks:
            await message.answer("📋 У вас пока нет задач.")
            return
        
        text = "📋 Ваши задачи:\n\n"
        status_emoji = {
            TaskStatus.ASSIGNED: "📌",
            TaskStatus.IN_PROGRESS: "🔄",
            TaskStatus.UNDER_REVIEW: "📸",
            TaskStatus.APPROVED_BY_FOREMAN: "✅",
            TaskStatus.PAID_BY_DIRECTOR: "💰"
        }
        
        for task in tasks[:10]:
            emoji = status_emoji.get(task.status, "❓")
            text += f"{emoji} #{task.id} {task.title}\n"
            text += f"   Статус: {task.status.value if hasattr(task.status, 'value') else task.status}\n"
            if task.cost:
                text += f"   Стоимость: {task.cost} руб.\n"
            text += "\n"
        
        await message.answer(text)


# === /new_task — создание задачи ===
@router.message(Command("new_task"))
async def cmd_new_task(message: types.Message, state: FSMContext):
    async for session in get_db():
        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.PTO, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для создания задач.")
            return
        
        await state.set_state(TaskCreation.waiting_for_title)
        await message.answer(
            "➕ Создание новой задачи\n\n"
            "Введите название задачи:"
        )


@router.message(TaskCreation.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(TaskCreation.waiting_for_description)
    await message.answer("📝 Введите описание задачи (или '-' чтобы пропустить):")


@router.message(TaskCreation.waiting_for_description)
async def process_description(message: types.Message, state: FSMContext):
    desc = message.text if message.text != "-" else None
    await state.update_data(description=desc)
    await state.set_state(TaskCreation.waiting_for_work_type)
    await message.answer("🔧 Введите вид работ (например: Покраска, Электромонтаж):")


@router.message(TaskCreation.waiting_for_work_type)
async def process_work_type(message: types.Message, state: FSMContext):
    await state.update_data(work_type=message.text)
    await state.set_state(TaskCreation.waiting_for_cost)
    await message.answer("💰 Введите стоимость работ (в рублях, или '-' чтобы пропустить):")


@router.message(TaskCreation.waiting_for_cost)
async def process_cost(message: types.Message, state: FSMContext):
    if message.text == "-":
        await state.update_data(cost=None)
    else:
        try:
            cost = float(message.text.replace(',', '.'))
            await state.update_data(cost=cost)
        except ValueError:
            await message.answer("❌ Введите корректное число (например: 5000)")
            return
    
    await state.set_state(TaskCreation.waiting_for_deadline)
    await message.answer("📅 Введите срок выполнения (в формате ДД.ММ.ГГГГ, или '-' чтобы пропустить):")


@router.message(TaskCreation.waiting_for_deadline)
async def process_deadline(message: types.Message, state: FSMContext):
    if message.text == "-":
        await state.update_data(deadline=None)
    else:
        try:
            deadline = datetime.strptime(message.text, "%d.%m.%Y")
            await state.update_data(deadline=deadline)
        except ValueError:
            await message.answer("❌ Неверный формат. Используйте ДД.ММ.ГГГГ (например: 31.12.2024)")
            return
    
    # Показываем список объектов
    async for session in get_db():
        objects = await session.execute(select(ConstructionObject))
        objects = objects.scalars().all()
        
        if not objects:
            await message.answer("❌ Нет доступных объектов. Сначала создайте объект через /add_object")
            await state.clear()
            return
        
        text = "🏗️ Выберите объект (введите ID):\n\n"
        for obj in objects:
            text += f"• {obj.id}: {obj.name} — {obj.address or 'адрес не указан'}\n"
        
        await state.set_state(TaskCreation.waiting_for_object)
        await message.answer(text)


@router.message(TaskCreation.waiting_for_object)
async def process_object(message: types.Message, state: FSMContext):
    try:
        object_id = int(message.text)
        await state.update_data(object_id=object_id)
        
        # Показываем список исполнителей
        async for session in get_db():
            users = await session.execute(
                select(User).where(User.role.in_([UserRole.WORKER, UserRole.ELECTRICIAN]))
            )
            users = users.scalars().all()
            
            if not users:
                await message.answer("❌ Нет доступных исполнителей. Добавьте рабочих через /add_user")
                await state.clear()
                return
            
            text = "👷 Выберите исполнителя (введите Telegram ID):\n\n"
            for u in users:
                text += f"• {u.telegram_id}: {u.full_name} — {u.role.value if hasattr(u.role, 'value') else u.role}\n"
            
            await state.set_state(TaskCreation.waiting_for_assignee)
            await message.answer(text)
    except ValueError:
        await message.answer("❌ Введите корректный ID объекта (число)")


@router.message(TaskCreation.waiting_for_assignee)
async def process_assignee(message: types.Message, state: FSMContext):
    try:
        assignee_id = int(message.text)
        data = await state.get_data()
        
        async for session in get_db():
            # Проверяем, что исполнитель существует
            executor = await session.execute(
                select(User).where(User.telegram_id == assignee_id)
            )
            if not executor.scalar_one_or_none():
                await message.answer("❌ Пользователь с таким ID не найден.")
                return
            
            task = Task(
                title=data['title'],
                description=data.get('description'),
                work_type=data.get('work_type'),
                cost=data.get('cost'),
                deadline=data.get('deadline'),
                status=TaskStatus.ASSIGNED,
                assigned_to=assignee_id,
                assigned_by=message.from_user.id,
                object_id=data.get('object_id')
            )
            session.add(task)
            await session.commit()
            
            deadline_str = task.deadline.strftime('%d.%m.%Y') if task.deadline else 'Не указан'
            cost_str = f"{task.cost} руб." if task.cost else "Не указана"
            
            await message.answer(
                f"✅ Задача создана!\n\n"
                f"📋 Название: {task.title}\n"
                f"📝 Описание: {task.description or '—'}\n"
                f"🔧 Вид работ: {task.work_type or '—'}\n"
                f"💰 Стоимость: {cost_str}\n"
                f"📅 Срок: {deadline_str}\n"
                f"👷 Исполнитель: {assignee_id}\n"
                f"🏗️ Объект: {task.object_id or '—'}\n"
                f"📌 Статус: {task.status.value if hasattr(task.status, 'value') else task.status}"
            )
            
            # Уведомляем исполнителя
            try:
                await message.bot.send_message(
                    assignee_id,
                    f"🔔 Вам назначена новая задача!\n\n"
                    f"📋 {task.title}\n"
                    f"📝 {task.description or '—'}\n"
                    f"💰 {cost_str}\n"
                    f"📅 Срок: {deadline_str}"
                )
            except Exception as e:
                logger.warning(f"Не удалось уведомить исполнителя {assignee_id}: {e}")
            
            await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя (число)")


# === /my_tasks — просмотр задач ===
@router.message(Command("my_tasks"))
async def cmd_my_tasks(message: types.Message):
    await my_tasks(message)


# === /approve_task — утверждение задачи (прораб) ===
@router.message(Command("approve_task"))
async def cmd_approve_task(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /approve_task [ID задачи]")
        return
    
    try:
        task_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID задачи должен быть числом")
        return
    
    async for session in get_db():
        # Проверяем права
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для утверждения задач.")
            return
        
        task = await session.get(Task, task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        
        if task.status != TaskStatus.UNDER_REVIEW:
            await message.answer(f"❌ Задача #{task_id} не на проверке. Текущий статус: {task.status.value if hasattr(task.status, 'value') else task.status}")
            return
        
        task.status = TaskStatus.APPROVED_BY_FOREMAN
        task.approved_by_foreman_at = datetime.utcnow()
        await session.commit()
        
        await message.answer(f"✅ Задача #{task_id} утверждена!")
        
        # Уведомляем исполнителя
        try:
            await message.bot.send_message(
                task.assigned_to,
                f"✅ Ваша задача #{task_id} утверждена прорабом!"
            )
        except:
            pass


# === /reject_task — отклонение задачи ===
@router.message(Command("reject_task"))
async def cmd_reject_task(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        await message.answer("❌ Использование: /reject_task [ID задачи] [причина]")
        return
    
    try:
        task_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID задачи должен быть числом")
        return
    
    reason = args[2] if len(args) > 2 else "Причина не указана"
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR, UserRole.FOREMAN]:
            await message.answer("❌ У вас нет прав для отклонения задач.")
            return
        
        task = await session.get(Task, task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        
        task.status = TaskStatus.IN_PROGRESS
        await session.commit()
        
        await message.answer(f"❌ Задача #{task_id} отклонена и возвращена в работу.\nПричина: {reason}")
        
        try:
            await message.bot.send_message(
                task.assigned_to,
                f"❌ Задача #{task_id} отклонена.\nПричина: {reason}"
            )
        except:
            pass


# === /pay_task — оплата задачи (гендир) ===
@router.message(Command("pay_task"))
async def cmd_pay_task(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /pay_task [ID задачи]")
        return
    
    try:
        task_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID задачи должен быть числом")
        return
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]:
            await message.answer("❌ У вас нет прав для оплаты задач.")
            return
        
        task = await session.get(Task, task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        
        if task.status != TaskStatus.APPROVED_BY_FOREMAN:
            await message.answer(f"❌ Задача #{task_id} ещё не утверждена прорабом.")
            return
        
        if not task.cost:
            await message.answer(f"❌ У задачи #{task_id} не указана стоимость.")
            return
        
        task.status = TaskStatus.PAID_BY_DIRECTOR
        task.paid_by_director_at = datetime.utcnow()
        
        # Создаём запись в зарплатной ведомости
        salary = SalaryLog(
            user_id=task.assigned_to,
            task_id=task.id,
            amount=task.cost
        )
        session.add(salary)
        await session.commit()
        
        await message.answer(
            f"💰 Задача #{task_id} оплачена!\n"
            f"💵 Сумма: {task.cost} руб.\n"
            f"👷 Исполнитель: {task.assigned_to}"
        )
        
        try:
            await message.bot.send_message(
                task.assigned_to,
                f"💰 Задача #{task_id} оплачена!\n💵 Сумма: {task.cost} руб."
            )
        except:
            pass


# === /adjust_cost — изменение стоимости задачи ===
@router.message(Command("adjust_cost"))
async def cmd_adjust_cost(message: types.Message):
    args = message.text.split()
    if len(args) < 3:
        await message.answer("❌ Использование: /adjust_cost [ID задачи] [новая цена]")
        return
    
    try:
        task_id = int(args[1])
        new_cost = float(args[2].replace(',', '.'))
    except ValueError:
        await message.answer("❌ ID задачи должен быть числом, цена — числом")
        return
    
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]:
            await message.answer("❌ У вас нет прав для изменения стоимости.")
            return
        
        task = await session.get(Task, task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        
        old_cost = task.cost
        task.cost = new_cost
        await session.commit()
        
        await message.answer(
            f"💵 Стоимость задачи #{task_id} изменена:\n"
            f"Было: {old_cost or '—'} руб.\n"
            f"Стало: {new_cost} руб."
        )


# === /start_task — начать выполнение задачи ===
@router.message(Command("start_task"))
async def cmd_start_task(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /start_task [ID задачи]")
        return
    
    try:
        task_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID задачи должен быть числом")
        return
    
    async for session in get_db():
        task = await session.get(Task, task_id)
        if not task:
            await message.answer(f"❌ Задача #{task_id} не найдена.")
            return
        
        if task.assigned_to != message.from_user.id:
            await message.answer("❌ Это не ваша задача.")
            return
        
        if task.status != TaskStatus.ASSIGNED:
            await message.answer(f"❌ Задача уже в статусе: {task.status.value if hasattr(task.status, 'value') else task.status}")
            return
        
        task.status = TaskStatus.IN_PROGRESS
        await session.commit()
        
        await message.answer(f"▶️ Задача #{task_id} начата! Статус: В работе")


# === /my_salary — мои начисления ===
@router.message(Command("my_salary"))
async def cmd_my_salary(message: types.Message):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user:
            await message.answer("❌ Вы не зарегистрированы.")
            return
        
        salaries = await session.execute(
            select(SalaryLog).where(SalaryLog.user_id == user.telegram_id)
        )
        salaries = salaries.scalars().all()
        
        if not salaries:
            await message.answer("💰 У вас пока нет начислений.")
            return
        
        total = sum(s.amount for s in salaries)
        text = f"💰 Ваши начисления:\n\n"
        for s in salaries:
            text += f"• Задача #{s.task_id}: {s.amount} руб.\n"
        text += f"\n💵 Всего: {total} руб."
        
        await message.answer(text)


# === /all_tasks — все задачи (для гендира/владельца) ===
@router.message(Command("all_tasks"))
async def cmd_all_tasks(message: types.Message):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role not in [UserRole.OWNER, UserRole.GENERAL_DIRECTOR]:
            await message.answer("❌ У вас нет прав для просмотра всех задач.")
            return
        
        tasks = await session.execute(
            select(Task).order_by(Task.created_at.desc())
        )
        tasks = tasks.scalars().all()
        
        if not tasks:
            await message.answer("📋 В системе нет задач.")
            return
        
        text = "📋 Все задачи:\n\n"
        status_emoji = {
            TaskStatus.ASSIGNED: "📌",
            TaskStatus.IN_PROGRESS: "🔄",
            TaskStatus.UNDER_REVIEW: "📸",
            TaskStatus.APPROVED_BY_FOREMAN: "✅",
            TaskStatus.PAID_BY_DIRECTOR: "💰"
        }
        
        for task in tasks[:20]:
            emoji = status_emoji.get(task.status, "❓")
            text += f"{emoji} #{task.id} {task.title}\n"
            text += f"   Статус: {task.status.value if hasattr(task.status, 'value') else task.status}\n"
            text += f"   Исполнитель: {task.assigned_to}\n\n"
        
        await message.answer(text)


# === /my_team_tasks — задачи бригады (для прораба) ===
@router.message(Command("my_team_tasks"))
async def cmd_my_team_tasks(message: types.Message):
    async for session in get_db():
        user = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user.scalar_one_or_none()
        if not user or user.role != UserRole.FOREMAN:
            await message.answer("❌ Эта команда только для прораба.")
            return
        
        # Получаем всех рабочих и электриков
        workers = await session.execute(
            select(User).where(User.role.in_([UserRole.WORKER, UserRole.ELECTRICIAN]))
        )
        workers = workers.scalars().all()
        worker_ids = [w.telegram_id for w in workers]
        
        if not worker_ids:
            await message.answer("👥 В вашей бригаде пока нет сотрудников.")
            return
        
        tasks = await session.execute(
            select(Task).where(Task.assigned_to.in_(worker_ids)).order_by(Task.created_at.desc())
        )
        tasks = tasks.scalars().all()
        
        if not tasks:
            await message.answer("📋 У вашей бригады пока нет задач.")
            return
        
        text = "📋 Задачи бригады:\n\n"
        for task in tasks[:15]:
            text += f"• #{task.id} {task.title}\n"
            text += f"  Исполнитель: {task.assigned_to}\n"
            text += f"  Статус: {task.status.value if hasattr(task.status, 'value') else task.status}\n\n"
        
        await message.answer(text)