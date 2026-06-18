from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import User, UserRole, Task, TaskStatus
from keyboards import get_main_menu_keyboard, get_cancel_keyboard
from config import settings
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)
router = Router()

# Конфигурация фото
MAX_PHOTO_SIZE = 1280  # максимальный размер в пикселях
THUMBNAIL_SIZE = 150   # миниатюра
MIN_PHOTOS = 3         # минимум фото для отчёта
UPLOAD_DIR = "uploads/photos"


class PhotoSubmissionStates(StatesGroup):
    waiting_for_task = State()
    waiting_for_photos = State()
    confirming = State()


@router.message(F.text == "📸 Сдать фото")
async def cmd_submit_photo(message: Message, state: FSMContext):
    """Начало отправки фотоотчёта"""
    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Вы не зарегистрированы")
            return

        # Получаем задачи "В работе"
        result = await session.execute(
            select(Task).where(
                Task.assigned_to == user.telegram_id,
                Task.status == TaskStatus.IN_PROGRESS
            )
        )
        tasks = result.scalars().all()

        if not tasks:
            await message.answer("❌ Нет задач в работе")
            return

        # Показываем список задач
        tasks_text = "📸 Выберите задачу для фотоотчёта:\n\n"
        for task in tasks:
            tasks_text += f"#{task.id} {task.title}\n"

        await message.answer(tasks_text)
        await state.set_state(PhotoSubmissionStates.waiting_for_task)


@router.message(PhotoSubmissionStates.waiting_for_task)
async def process_photo_task(message: Message, state: FSMContext):
    """Обработка выбора задачи"""
    try:
        task_id = int(message.text.split()[0].replace("#", ""))
    except (ValueError, IndexError):
        await message.answer("❌ Неверный формат. Введите номер задачи")
        return

    async for session in get_db():
        from sqlalchemy import select

        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        task = result.scalar_one_or_none()

        if not task or task.assigned_to != message.from_user.id:
            await message.answer("❌ Задача не найдена или не принадлежит вам")
            return

        await state.update_data(task_id=task_id, photos=[])
        await message.answer(
            f"📸 Отправка фото для задачи #{task_id}\n\n"
            f"Отправьте минимум {MIN_PHOTOS} фото.\n"
            f"Когда закончите, нажмите 'Завершить'",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(PhotoSubmissionStates.waiting_for_photos)


@router.message(PhotoSubmissionStates.waiting_for_photos, F.photo)
async def process_photo(message: Message, state: FSMContext, session: AsyncSession):
    """Обработка фото"""
    data = await state.get_data()
    photos = data.get("photos", [])

    # Сохраняем фото
    photo = message.photo[-1]  # Берем самое большое
    file_id = photo.file_id

    # Создаём папку если нет
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # Скачиваем фото
    from aiogram import Bot
    bot = Bot(token=settings.BOT_TOKEN)
    file = await bot.get_file(file_id)
    file_path = file.file_path

    # Генерируем имя файла
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{message.from_user.id}_{timestamp}_{len(photos)}.jpg"
    full_path = os.path.join(UPLOAD_DIR, filename)

    # Скачиваем файл
    await bot.download_file(file_path, full_path)

    # Ресайз через PIL (в отдельном потоке)
    import asyncio
    from PIL import Image

    def resize_photo():
        img = Image.open(full_path)
        # Ресайз с сохранением пропорций
        img.thumbnail((MAX_PHOTO_SIZE, MAX_PHOTO_SIZE), Image.Resampling.LANCZOS)
        img.save(full_path, "JPEG", quality=85)

        # Создаём миниатюру
        thumb = img.copy()
        thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
        thumb_path = full_path.replace(".jpg", "_thumb.jpg")
        thumb.save(thumb_path, "JPEG", quality=80)

    await asyncio.to_thread(resize_photo)

    # Сохраняем в состояние
    photos.append({
        "file_id": file_id,
        "file_path": full_path,
        "timestamp": datetime.utcnow().isoformat()
    })

    await state.update_data(photos=photos)

    # Проверяем количество
    if len(photos) >= MIN_PHOTOS:
        await message.answer(
            f"✅ Фото сохранено ({len(photos)}/{MIN_PHOTOS})\n\n"
            f"Вы можете отправить ещё фото или нажать 'Завершить'",
            reply_markup=get_cancel_keyboard()
        )
    else:
        await message.answer(
            f"✅ Фото сохранено ({len(photos)}/{MIN_PHOTOS})\n"
            f"Отправьте ещё хотя бы {MIN_PHOTOS - len(photos)} фото",
            reply_markup=get_cancel_keyboard()
        )


@router.message(PhotoSubmissionStates.waiting_for_photos, F.text == "✅ Завершить")
async def finish_photo_submission(message: Message, state: FSMContext, session: AsyncSession):
    """Завершение отправки фото"""
    data = await state.get_data()
    photos = data.get("photos", [])
    task_id = data.get("task_id")

    if len(photos) < MIN_PHOTOS:
        await message.answer(
            f"❌ Нужно минимум {MIN_PHOTOS} фото. Отправлено: {len(photos)}"
        )
        return

    # Обновляем задачу
    from sqlalchemy import select
    result = await session.execute(
        select(Task).where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()

    if task:
        task.status = TaskStatus.UNDER_REVIEW
        task.photos_metadata = photos
        await session.commit()

        # Уведомляем прораба
        try:
            from aiogram import Bot
            bot = Bot(token=settings.BOT_TOKEN)
            await bot.send_message(
                task.assigned_by,
                f"🔍 Задача #{task_id} отправлена на проверку!\n"
                f"Фотоотчёт: {len(photos)} фото"
            )
        except Exception as e:
            logger.error(f"Failed to notify foreman: {e}")

        await message.answer(
            f"✅ Фотоотчёт отправлен!\n"
            f"Задача #{task_id} перешла в статус 'На проверке'",
            reply_markup=get_main_menu_keyboard(UserRole.WORKER)
        )

    await state.clear()


@router.message(PhotoSubmissionStates.waiting_for_photos, F.text == "❌ Отмена")
async def cancel_photo_submission(message: Message, state: FSMContext):
    """Отмена отправки фото"""
    await state.clear()
    await message.answer("❌ Отправка фото отменена", reply_markup=get_main_menu_keyboard(UserRole.WORKER))