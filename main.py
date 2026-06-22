import asyncio
import os
import fcntl
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
import uvicorn
from loguru import logger
from config import settings
from database import init_db
from handlers import user, task, photo, material, tool, order, admin, safety

# Инициализация бота
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

# PID файл для гарантии единственного экземпляра
PID_FILE = "/tmp/benefon_bot.pid"

def check_single_instance():
    """Проверяет, что запущен только один экземпляр бота"""
    try:
        fp = open(PID_FILE, 'w')
        fcntl.flock(fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fp.write(str(os.getpid()))
        fp.flush()
        logger.info(f"Single instance lock acquired (PID: {os.getpid()})")
        return True
    except IOError:
        logger.error("Another instance of the bot is already running. Exiting.")
        return False

# Инициализация FastAPI для health checks (чтобы Render видел открытый порт)
app = FastAPI(title="Benefon Bot Health Check")

@app.get("/")
@app.get("/health")
async def health_check():
    """Health check endpoint для Render"""
    return {"status": "ok", "message": "Benefon Bot is running"}

async def start_bot():
    """Запускает бота в режиме polling"""
    if not check_single_instance():
        return
    
    logger.info("Starting Benefon Bot...")
    await init_db()
    logger.info("Database initialized")
    scheduler.start()
    logger.info("Scheduler started")
    await bot.delete_webhook()
    logger.info("Webhook deleted")
    logger.info("✅ Benefon Bot started in polling mode!")
    
    await dp.start_polling(bot)

async def start_webserver():
    """Запускает веб-сервер для health checks"""
    config = uvicorn.Config(app, host="0.0.0.0", port=10000, log_level="info")
    server = uvicorn.Server(config)
    logger.info("Starting health check server on port 10000...")
    await server.serve()

async def main():
    """Запускает бота и веб-сервер параллельно"""
    await asyncio.gather(
        start_bot(),
        start_webserver()
    )

if __name__ == "__main__":
    asyncio.run(main())