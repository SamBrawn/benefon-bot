import asyncio
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from config import settings
from database import init_db
from handlers import user, task, photo, material, tool, order, admin, safety

# Инициализация
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


async def on_startup():
    logger.info("Starting Benefon Bot (polling mode)...")
    await init_db()
    logger.info("Database initialized")
    scheduler.start()
    logger.info("Scheduler started")
    await bot.delete_webhook()
    logger.info("Webhook deleted")
    logger.info("✅ Benefon Bot started in polling mode!")


async def main():
    await on_startup()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())