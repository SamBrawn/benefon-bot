import asyncio
import json
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from config import settings
from database import engine, init_db
from handlers import user, task, photo, material, tool, order, admin, safety

bot = Bot(token=settings.BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# Регистрация роутеров
dp.include_router(user.router)
dp.include_router(task.router)
dp.include_router(photo.router)
dp.include_router(material.router)
dp.include_router(tool.router)
dp.include_router(order.router)
dp.include_router(admin.router)
dp.include_router(safety.router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Benefon Bot...")
    try:
        await init_db()
        logger.info("Database initialized")
        scheduler.start()
        logger.info("Scheduler started")
        await bot.set_webhook(
            url=f"{settings.WEBHOOK_URL}/webhook",
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"Webhook set to {settings.WEBHOOK_URL}/webhook")
        yield
    except Exception as e:
        logger.error(f"Startup error: {e}")
        yield
    finally:
        logger.info("Shutting down...")
        try:
            await bot.delete_webhook()
            await bot.session.close()
        except:
            pass
        try:
            if scheduler and scheduler.running:
                scheduler.shutdown()
        except:
            pass
        try:
            await engine.dispose()
        except:
            pass
        logger.info("✅ Shutdown complete")


# Создаём app ПОСЛЕ lifespan, чтобы избежать проблем с порядком
app = FastAPI(title="Benefon Bot", lifespan=lifespan)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}")
    return Response(content=json.dumps({"ok": False, "error": str(exc)}), status_code=200)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        if not body:
            return {"ok": False, "error": "Empty body"}
        update_data = json.loads(body)
        update = types.Update(**update_data)
        asyncio.create_task(safe_feed_update(update))
        return {"ok": True}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return {"ok": False, "error": "Invalid JSON"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}


async def safe_feed_update(update: types.Update):
    try:
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.error(f"Feed update error: {e}")


@app.get("/")
async def root():
    return {"status": "ok", "message": "Benefon Bot is running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# Расписания
@scheduler.scheduled_job('cron', hour=9, minute=0)
async def daily_digest():
    from services.notification_service import NotificationService
    service = NotificationService()
    await service.send_daily_digest()
    logger.info("Daily digest sent")


@scheduler.scheduled_job('cron', hour=20, minute=0)
async def owner_report():
    from services.notification_service import NotificationService
    service = NotificationService()
    await service.send_owner_report()
    logger.info("Owner report sent")


@scheduler.scheduled_job('cron', hour=0, minute=0)
async def cleanup_photos():
    from services.photo_service import PhotoService
    PhotoService.cleanup_old_photos(days=90)
    logger.info("Old photos cleaned up")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 10000))
    host = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
    
    logger.info(f"Starting server on {host}:{port}...")
    # Передаём ОБЪЕКТ app, а не строку "main:app"!
    # Это предотвращает двойной импорт main.py и ошибку "Router is already attached"
    uvicorn.run(app, host=host, port=port, log_level="info")
    
    # Важно: Render сканирует порт 10000, связка через app объект
