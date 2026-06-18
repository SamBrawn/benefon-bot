import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI, Request
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uvicorn
from loguru import logger

from config import settings
from database import init_db
from handlers import user, task, photo, material, tool, order, admin

# Настройка логирования
logger.add(
    "logs/bot.log",
    rotation="10 MB",
    retention="30 days",
    encoding="utf-8",
    level=settings.LOG_LEVEL
)

# Инициализация
bot = Bot(token=settings.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Регистрация хэндлеров
dp.include_router(user.router)
dp.include_router(task.router)
dp.include_router(photo.router)
dp.include_router(material.router)
dp.include_router(tool.router)
dp.include_router(order.router)
dp.include_router(admin.router)

# Lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    logger.info("Starting Benefon Bot...")

    # Инициализация БД
    await init_db()
    logger.info("Database initialized")

    # Запуск планировщика
    scheduler.start()
    logger.info("Scheduler started")

    # Настройка webhook/polling
    if not settings.LOCAL_DEBUG:
        await bot.set_webhook(url=f"{settings.WEBHOOK_URL}/webhook")
        logger.info(f"Webhook set to {settings.WEBHOOK_URL}/webhook")
    else:
        await bot.delete_webhook()
        asyncio.create_task(dp.start_polling(bot))
        logger.info("Bot started in polling mode")
    
    yield  # Бот работает
    
    # Shutdown
    logger.info("Shutting down...")
    await bot.delete_webhook()
    await bot.session.close()
    scheduler.shutdown()
    logger.info("✅ Shutdown complete")

# Создание FastAPI приложения с lifespan
app = FastAPI(title="Benefon Bot", lifespan=lifespan)

# Подключение веб-панели
from web.app import app as web_app
app.mount("/", web_app)


# Webhook эндпоинт
@app.post("/webhook")
async def webhook(request: Request):
    """Webhook для Telegram"""
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}


# Расписания
@scheduler.scheduled_job('cron', hour=9, minute=0)
async def daily_digest():
    """Ежедневный дайджест в 09:00"""
    from services.notification_service import NotificationService
    service = NotificationService()
    await service.send_daily_digest()
    logger.info("Daily digest sent")


@scheduler.scheduled_job('cron', hour=20, minute=0)
async def owner_report():
    """Отчёт владельцу в 20:00"""
    from services.notification_service import NotificationService
    service = NotificationService()
    await service.send_owner_report()
    logger.info("Owner report sent")


@scheduler.scheduled_job('cron', hour=0, minute=0)
async def cleanup_photos():
    """Очистка старых фото (раз в день)"""
    from services.photo_service import PhotoService
    PhotoService.cleanup_old_photos(days=90)
    logger.info("Old photos cleaned up")


if __name__ == "__main__":
    # Создаём папку для логов
    import os
    os.makedirs("logs", exist_ok=True)
    os.makedirs("uploads/photos", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    if settings.LOCAL_DEBUG:
        uvicorn.run(app, host=settings.WEB_SERVER_HOST, port=settings.WEB_SERVER_PORT)
    else:
        uvicorn.run(app, host=settings.WEB_SERVER_HOST, port=settings.WEB_SERVER_PORT)