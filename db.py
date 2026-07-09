from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import settings
import redis.asyncio as redis
import os

# Создаем движок в зависимости от типа базы данных
if settings.is_sqlite:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False}
    )
else:
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20
    )

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Redis для кэша и состояний
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_pool = None

async def get_redis():
    """Возвращает подключение к Redis (ленивая инициализация)"""
    global redis_pool
    if redis_pool is None:
        redis_pool = redis.from_url(REDIS_URL, decode_responses=True)
    return redis_pool

async def close_redis():
    global redis_pool
    if redis_pool:
        await redis_pool.close()
        redis_pool = None

async def get_session():
    """Генератор асинхронных сессий"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def close_db():
    """Закрывает движок БД"""
    await engine.dispose()
