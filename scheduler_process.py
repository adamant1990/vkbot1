import datetime
from sqlalchemy import select, and_
from db import async_session_maker
from models import Trip, TripStatus, Booking, BookingStatus, User, Subscription, PendingRating
from loguru import logger
from vkbottle import API
from config import settings

async def complete_trips_and_request_ratings():
    """Завершает поездки через 24 часа, сохраняет ожидающие оценки и чистит старые подписки"""
    logger.info("Scheduler: checking trips to complete...")
    
    async with async_session_maker() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(hours=24)
        
        # === Очистка старых подписок ===
        old_subs_result = await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.date.isnot(None),
                    Subscription.date < now.replace(tzinfo=None)
                )
            )
        )
        old_subs = old_subs_result.scalars().all()
        if old_subs:
            for sub in old_subs:
                await session.delete(sub)
            await session.commit()
            logger.info(f"Scheduler: cleaned {len(old_subs)} old subscriptions")
        
        # === Завершение поездок ===
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
                for booking in accepted_bookings:
                    passenger = await session.get(User, booking.passenger_id)
                    if passenger:
                        # Сохраняем ожидающую оценку для водителя
                        pending = PendingRating(
                            from_user_vk_id=driver.vk_id,
                            to_user_id=passenger.id,
                            trip_id=booking.id,
                            target_name=f"{passenger.first_name} {passenger.last_name}"
                        )
                        session.add(pending)
                        logger.info(f"Pending rating saved for driver {driver.vk_id} -> passenger {passenger.id}")
            
            for booking in accepted_bookings:
                passenger = await session.get(User, booking.passenger_id)
                if passenger and driver:
                    # Сохраняем ожидающую оценку для пассажира
                    pending = PendingRating(
                        from_user_vk_id=passenger.vk_id,
                        to_user_id=driver.id,
                        trip_id=booking.id,
                        target_name=f"{driver.first_name} {driver.last_name}"
                    )
                    session.add(pending)
                    logger.info(f"Pending rating saved for passenger {passenger.vk_id} -> driver {driver.id}")
        
        await session.commit()
        logger.info(f"Scheduler: completed {len(trips_to_complete)} trips")
