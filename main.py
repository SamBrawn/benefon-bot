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

# Регистрация роутеров (ТОЛЬКО ОДИН РАЗ)
dp.include_router(user.router)
dp.include_router(task.router)
dp.include_router(photo.router)
dp.include_router(material.router)
dp.include_router(tool.router)
dp.include_router(order.router)
dp.include_router(admin.router)
dp.include_router(safety.router)


async def on_startup():
    logger.info("Starting Benefon Bot...")
    await init_db()
    logger.info("Database initialized")
    scheduler.start()
    logger.info("Scheduler started")

    if not settings.LOCAL_DEBUG:
        await bot.set_webhook(
            url=f"{settings.WEBHOOK_URL}/webhook",
            allowed_updates=["message", "callback_query"]
        )
        logger.info(f"Webhook set to {settings.WEBHOOK_URL}/webhook")
    else:
        await bot.delete_webhook()
        asyncio.create_task(dp.start_polling(bot))
        logger.info("Bot started in polling mode")

    logger.info("✅ Benefon Bot started!")


async def main():
    await on_startup()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())