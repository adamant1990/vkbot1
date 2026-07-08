import datetime
from sqlalchemy import select, and_
from db import async_session_maker
from models import Trip, TripStatus, Booking, BookingStatus, User
from loguru import logger
from vkbottle import API
from config import settings

async def complete_trips_and_request_ratings():
    """Завершает поездки через 24 часа после отправления и запрашивает оценки"""
    logger.info("Scheduler: checking trips to complete...")
    
    async with async_session_maker() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(hours=24)
        
        # Находим активные поездки, которые пора завершить
        result = await session.execute(
            select(Trip).where(
                and_(
                    Trip.status == TripStatus.active,
                    Trip.departure_time <= cutoff
                )
            )
        )
        trips_to_complete = result.scalars().all()
        
        if not trips_to_complete:
            logger.info("Scheduler: no trips to complete")
            return
        
        logger.info(f"Scheduler: completing {len(trips_to_complete)} trips")
        
        api = API(token=settings.VK_GROUP_TOKEN)
        
        for trip in trips_to_complete:
            trip.status = TripStatus.completed
            logger.info(f"Trip {trip.id} marked as completed")
            
            # Получаем подтвержденных пассажиров
            bookings_result = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip.id,
                        Booking.status == BookingStatus.accepted
                    )
                )
            )
            accepted_bookings = bookings_result.scalars().all()
            
            # Получаем водителя
            driver = await session.get(User, trip.driver_id)
            
            if driver:
                # Отправляем запрос на оценку водителю (оценка пассажиров)
                for booking in accepted_bookings:
                    passenger = await session.get(User, booking.passenger_id)
                    if passenger:
                        try:
                            from handlers.menu import send_rating_request
                            await send_rating_request(
                                user_id=driver.vk_id,
                                trip_id=trip.id,
                                target_id=passenger.id,
                                target_name=f"{passenger.first_name} {passenger.last_name}"
                            )
                            logger.info(f"Rating request sent to driver {driver.vk_id} for passenger {passenger.id}")
                        except Exception as e:
                            logger.error(f"Failed to send rating request to driver: {e}")
            
            # Отправляем запрос на оценку каждому пассажиру (оценка водителя)
            for booking in accepted_bookings:
                passenger = await session.get(User, booking.passenger_id)
                if passenger:
                    try:
                        from handlers.menu import send_rating_request
                        await send_rating_request(
                            user_id=passenger.vk_id,
                            trip_id=trip.id,
                            target_id=driver.id if driver else None,
                            target_name=f"{driver.first_name} {driver.last_name}" if driver else "водитель"
                        )
                        logger.info(f"Rating request sent to passenger {passenger.vk_id} for driver {driver.id if driver else 'unknown'}")
                    except Exception as e:
                        logger.error(f"Failed to send rating request to passenger: {e}")
        
        await session.commit()
        logger.info(f"Scheduler: completed {len(trips_to_complete)} trips")
