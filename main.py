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

# Глобальный обработчик ошибок FastAPI
app = FastAPI(title="Benefon Bot")

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {exc}")
    return Response(content=json.dumps({"ok": False, "error": str(exc)}), status_code=200)

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Benefon Bot...")
    try:
        await init_db()
        logger.info("Database initialized")
        
        scheduler.start()
        logger.info("Scheduler started")
        
        if not settings.LOCAL_DEBUG:
            try:
                await bot.set_webhook(
                    url=f"{settings.WEBHOOK_URL}/webhook",
                    allowed_updates=["message", "callback_query"]
                )
                logger.info(f"Webhook set to {settings.WEBHOOK_URL}/webhook")
            except Exception as e:
                logger.error(f"Failed to set webhook: {e}")
        else:
            await bot.delete_webhook()
            asyncio.create_task(dp.start_polling(bot))
            logger.info("Bot started in polling mode")
        
        yield
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        yield
    finally:
        logger.info("Shutting down...")
        try:
            await bot.delete_webhook()
            await bot.session.close()
        except Exception as e:
            logger.error(f"Bot shutdown error: {e}")
        
        try:
            if scheduler:
                scheduler.shutdown()
                logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Scheduler shutdown error: {e}")
        
        try:
            await engine.dispose()
            logger.info("Database engine disposed")
        except Exception as e:
            logger.error(f"Database shutdown error: {e}")
        
        logger.info("✅ Shutdown complete")

app = FastAPI(title="Benefon Bot", lifespan=lifespan)

# Webhook эндпоинт
@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        if not body:
            logger.warning("Empty webhook request body")
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
        logger.error(f"Feed update error: {e}", exc_info=True)
        try:
            if update.message and update.message.from_user:
                await bot.send_message(
                    update.message.from_user.id,
                    "⚠️ Произошла ошибка. Попробуйте ещё раз."
                )
        except:
            pass

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", 8000)))
    host = os.getenv("WEB_SERVER_HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
