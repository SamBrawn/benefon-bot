from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from config import settings
from loguru import logger

# Формируем URL с asyncpg
DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Правильная настройка engine с NullPool
# NullPool отключает пулинг - каждое соединение создаётся и закрывается отдельно
# Это предотвращает ошибку "connection is closed" в async окружении
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,      # Только poolclass, без pool_size и max_overflow
    pool_pre_ping=True,      # Проверка соединения перед использованием
    pool_recycle=3600        # Переподключение каждый час
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Создание всех таблиц (для разработки)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)