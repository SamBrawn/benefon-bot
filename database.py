from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from config import settings
from loguru import logger

# Формируем URL с asyncpg
DATABASE_URL = settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Создаем engine с настройками пула
# NullPool отключает пулинг - каждое соединение создаётся и закрывается отдельно
# Это предотвращает ошибку "connection is closed" в async окружении
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,      # Проверка соединения перед использованием
    pool_recycle=3600,        # Переподключение каждый час
    pool_timeout=30,          # Таймаут получения соединения
    poolclass=NullPool        # Отключаем пул для предотвращения "connection is closed"
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