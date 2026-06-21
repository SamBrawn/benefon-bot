from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from config import settings
from loguru import logger

# Функция для очистки URL от sslmode
def clean_db_url(url: str) -> str:
    """Удаляет параметр sslmode из URL."""
    if "?" in url:
        base, params = url.split("?", 1)
        cleaned_params = "&".join([p for p in params.split("&") if not p.startswith("sslmode=")])
        return f"{base}?{cleaned_params}" if cleaned_params else base
    return url

# Очищаем URL
DATABASE_URL = clean_db_url(settings.DATABASE_URL).replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"ssl": True}
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
