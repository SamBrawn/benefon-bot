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
from handlers import user, task, photo, material, tool, order, admin, safety

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

# Регистрация хэндлеров (выполняется 1 раз при импорте)
dp.include_router(user.router)
dp.include_router(task.router)
dp.include_router(photo.router)
dp.include_router(material.router)
dp.include_router(tool.router)
dp.include_router(order.router)
dp.include_router(admin.router)
dp.include_router(safety.router)

# Lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения"""
    # Startup
    logger.info("Starting Benefon Bot...")
    
    try:
        # Инициализация БД
        await init_db()
        logger.info("Database initialized")
        
        # Запуск планировщика
        scheduler.start()
        logger.info("Scheduler started")
        
        # Настройка webhook/polling
        if not settings.LOCAL_DEBUG:
            try:
                await bot.set_webhook(
                    url=f"{settings.WEBHOOK_URL}/webhook",
                    allowed_updates=["message", "callback_query"]
                )
                logger.info(f"Webhook set to {settings.WEBHOOK_URL}/webhook")
            except Exception as e:
                logger.error(f"Failed to set webhook: {e}")
                # Не падаем, продолжаем работу
        else:
            await bot.delete_webhook()
            asyncio.create_task(dp.start_polling(bot))
            logger.info("Bot started in polling mode")
        
        yield  # Бот работает
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        # Не падаем, продолжаем работу
        yield
    finally:
        # Shutdown
        logger.info("Shutting down...")
        try:
            await bot.delete_webhook()
            await bot.session.close()
            scheduler.shutdown()
            logger.info("✅ Shutdown complete")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

# Создание FastAPI приложения с lifespan
app = FastAPI(title="Benefon Bot", lifespan=lifespan)

# Webhook эндпоинт (должен быть перед монтированием веб-панели)
from aiogram import types
from fastapi import Request
import json

@app.post("/webhook")
async def webhook(request: Request):
    """Webhook для Telegram"""
    try:
        body = await request.body()
        if not body:
            logger.warning("Empty webhook request body")
            return {"ok": False, "error": "Empty body"}
        
        update_data = json.loads(body)
        update = types.Update(**update_data)
        
        try:
            await dp.feed_update(bot, update)
        except Exception as e:
            logger.error(f"Feed update error: {e}")
            # Не падаем, продолжаем работу
            return {"ok": False, "error": str(e)}
        
        return {"ok": True}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {"ok": False, "error": "Invalid JSON"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # НЕ ПАДАЕМ, возвращаем 200 OK
        return {"ok": False, "error": str(e)}

# Подключение веб-панели
from web.app import app as web_app
app.mount("/", web_app)


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


# Запуск приложения (используется Render.com)
import os

if __name__ == "__main__":
    # Создаём папку для логов
    os.makedirs("logs", exist_ok=True)
    os.makedirs("uploads/photos", exist_ok=True)
    os.makedirs("reports", exist_ok=True)

    # Render использует переменную PORT
    port = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", "8000")))
    host = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
    
    # Передаём объект app напрямую, чтобы uvicorn не переимпортировал модуль
    uvicorn.run(app, host=host, port=port, reload=False)
