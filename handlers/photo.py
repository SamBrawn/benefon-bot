from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from database import get_db
from models import Task, TaskStatus, User
import logging
import os

logger = logging.getLogger(__name__)
router = Router()


# === /submit_photo — сдать фотоотчёт ===
@router.message(Command("submit_photo"))
async def cmd_submit_photo(message: types.Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Использование: /submit_photo [ID задачи]\n\nЗатем отправьте фото.")
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
        
        if task.status != TaskStatus.IN_PROGRESS:
            await message.answer(f"❌ Задача не в статусе 'В работе'. Текущий: {task.status.value if hasattr(task.status, 'value') else task.status}")
            return
        
        # Сохраняем ID задачи в контекст для следующего сообщения с фото
        await message.answer(f"📸 Отправьте фото для задачи #{task_id}:")


# === Обработка фотографий ===
@router.message(F.photo)
async def handle_photo(message: types.Message):
    # Получаем информацию о фото
    photo = message.photo[-1]  # Берём самое большое фото
    
    # Создаём директорию для фото, если её нет
    os.makedirs("uploads/photos", exist_ok=True)
    
    # Сохраняем файл
    file_id = photo.file_id
    file_path = f"uploads/photos/{file_id}.jpg"
    
    # Скачиваем файл
    file = await message.bot.get_file(file_id)
    await message.bot.download_file(file.file_path, destination=file_path)
    
    # Ищем задачу, к которой относится фото
    # Проверяем, есть ли у пользователя задача в статусе "В работе"
    async for session in get_db():
        tasks = await session.execute(
            select(Task).where(
                (Task.assigned_to == message.from_user.id) &
                (Task.status == TaskStatus.IN_PROGRESS)
            )
        )
        tasks = tasks.scalars().all()
        
        if not tasks:
            await message.answer("📸 Фото сохранено, но у вас нет активных задач для привязки.")
            return
        
        # Берём последнюю активную задачу
        task = tasks[-1]
        
        # Сохраняем метаданные фото в задачу
        import json
        metadata = {
            "file_id": file_id,
            "file_path": file_path,
            "timestamp": message.date.isoformat() if message.date else None
        }
        
        if task.photos_metadata:
            photos = task.photos_metadata
            if isinstance(photos, str):
                photos = json.loads(photos)
            photos.append(metadata)
        else:
            photos = [metadata]
        
        task.photos_metadata = photos
        task.status = TaskStatus.UNDER_REVIEW
        await session.commit()
        
        await message.answer(
            f"✅ Фотоотчёт принят для задачи #{task.id}!\n"
            f"📌 Статус: На проверке"
        )
        
        # Уведомляем создателя задачи
        try:
            await message.bot.send_message(
                task.assigned_by,
                f"📸 Фотоотчёт по задаче #{task.id}\n"
                f"👷 Исполнитель: {message.from_user.id}\n"
                f"📌 Статус: На проверке\n\n"
                f"/approve_task {task.id} — Утвердить\n"
                f"/reject_task {task.id} [причина] — Отклонить"
            )
        except Exception as e:
            logger.warning(f"Не удалось уведомить создателя задачи: {e}")