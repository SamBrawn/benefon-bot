from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from config import settings
from loguru import logger
import re

def clean_db_url(url: str) -> str:
    """Удаляет все параметры sslmode из URL."""
    if "?" in url:
        base, params = url.split("?", 1)
        params_list = [p for p in params.split("&") if not p.startswith("sslmode=")]
        return f"{base}?{'&'.join(params_list)}" if params_list else base
    return url

# Очищаем URL от sslmode
CLEAN_URL = clean_db_url(settings.DATABASE_URL)
DATABASE_URL = CLEAN_URL.replace("postgresql://", "postgresql+asyncpg://")

logger.info(f"Database URL cleaned (sslmode removed)")

# Создаём engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    pool_pre_ping=True,
    pool_recycle=3600
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

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
    from models import Base as ModelsBase
    async with engine.begin() as conn:
        await conn.run_sync(ModelsBase.metadata.create_all)
    logger.info("Database initialized")