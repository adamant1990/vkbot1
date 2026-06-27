from sqlalchemy import select
from models import User, Trip, Booking

async def get_user_by_vk_id(session, vk_id: int) -> User | None:
    """Получает пользователя по VK ID"""
    result = await session.execute(
        select(User).where(User.vk_id == vk_id)
    )
    return result.scalar()

async def get_user_by_id(session, user_id: int) -> User | None:
    """Получает пользователя по первичному ключу"""
    return await session.get(User, user_id)

async def get_trip_by_id(session, trip_id: int) -> Trip | None:
    """Получает поездку по ID"""
    return await session.get(Trip, trip_id)

async def get_booking_by_id(session, booking_id: int) -> Booking | None:
    """Получает бронирование по ID"""
    return await session.get(Booking, booking_id)

async def update_user_rating(session, user_id: int):
    """Пересчитывает рейтинг пользователя на основе всех оценок"""
    from models import Rating
    from sqlalchemy import func
    
    result = await session.execute(
        select(func.avg(Rating.value), func.count(Rating.id))
        .where(Rating.to_user_id == user_id)
    )
    avg_rating, count = result.one()
    
    user = await session.get(User, user_id)
    if user:
        if avg_rating is not None:
            user.rating = round(float(avg_rating), 1)
            user.rating_count = count
        else:
            user.rating = None
            user.rating_count = 0
        await session.commit()

async def get_setting(session, key: str, default: str = None) -> str:
    """Получает значение настройки по ключу"""
    from models import Settings
    result = await session.execute(
        select(Settings).where(Settings.key == key)
    )
    setting = result.scalar()
    return setting.value if setting else default

async def set_setting(session, key: str, value: str):
    """Устанавливает или обновляет значение настройки"""
    from models import Settings
    result = await session.execute(
        select(Settings).where(Settings.key == key)
    )
    setting = result.scalar()
    if setting:
        setting.value = value
    else:
        setting = Settings(key=key, value=value)
        session.add(setting)
    await session.commit()