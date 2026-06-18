import os
import asyncio
from PIL import Image
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Конфигурация
MAX_PHOTO_SIZE = 1280  # максимальный размер в пикселях
THUMBNAIL_SIZE = 150   # миниатюра
UPLOAD_DIR = "uploads/photos"


class PhotoService:
    """Сервис для работы с фотографиями"""

    @staticmethod
    def save_photo(file_path: str, user_id: int, timestamp: str, index: int) -> dict:
        """
        Сохраняет фото с ресайзом и созданием миниатюры
        Returns: dict с информацией о сохранённых файлах
        """
        try:
            # Создаём папку если нет
            os.makedirs(UPLOAD_DIR, exist_ok=True)

            # Генерируем имя файла
            filename = f"{user_id}_{timestamp}_{index}.jpg"
            full_path = os.path.join(UPLOAD_DIR, filename)

            # Ресайз
            img = Image.open(file_path)
            img.thumbnail((MAX_PHOTO_SIZE, MAX_PHOTO_SIZE), Image.Resampling.LANCZOS)
            img.save(full_path, "JPEG", quality=85)

            # Создаём миниатюру
            thumb = img.copy()
            thumb.thumbnail((THUMBNAIL_SIZE, THUMBNAIL_SIZE), Image.Resampling.LANCZOS)
            thumb_path = full_path.replace(".jpg", "_thumb.jpg")
            thumb.save(thumb_path, "JPEG", quality=80)

            logger.info(f"Photo saved: {filename}")

            return {
                "file_path": full_path,
                "thumb_path": thumb_path,
                "filename": filename
            }

        except Exception as e:
            logger.error(f"Failed to save photo: {e}")
            return {}

    @staticmethod
    async def save_photo_async(file_path: str, user_id: int, timestamp: str, index: int) -> dict:
        """Асинхронная версия сохранения фото"""
        return await asyncio.to_thread(
            PhotoService.save_photo,
            file_path, user_id, timestamp, index
        )

    @staticmethod
    def cleanup_old_photos(days: int = 90):
        """
        Удаление старых фото
        Args:
            days: удалить фото старше N дней
        """
        try:
            if not os.path.exists(UPLOAD_DIR):
                return

            from datetime import datetime, timedelta
            cutoff_date = datetime.now() - timedelta(days=days)

            deleted_count = 0
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                if os.path.isfile(file_path):
                    file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                    if file_time < cutoff_date:
                        os.remove(file_path)
                        deleted_count += 1

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old photos")

        except Exception as e:
            logger.error(f"Failed to cleanup photos: {e}")