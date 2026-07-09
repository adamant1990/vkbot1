import datetime
from sqlalchemy import select, and_
from db import async_session_maker
from models import Trip, TripStatus, Booking, BookingStatus, User, Subscription, PendingRating
from loguru import logger
from vkbottle import API, Keyboard, Text, KeyboardButtonColor
from config import settings

async def complete_trips_and_request_ratings():
    """Завершает поездки через 24 часа, отправляет запросы оценок и чистит старые подписки"""
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
        
        api = API(token=settings.VK_GROUP_TOKEN)
        
        for trip in trips_to_complete:
            trip.status = TripStatus.completed
            logger.info(f"Trip {trip.id} marked as completed")
            
            bookings_result = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip.id,
                        Booking.status == BookingStatus.accepted
                    )
                )
            )
            accepted_bookings = bookings_result.scalars().all()
            
            driver = await session.get(User, trip.driver_id)
            
            if driver:
                for booking in accepted_bookings:
                    passenger = await session.get(User, booking.passenger_id)
                    if passenger:
                        # Сохраняем PendingRating для БД
                        pending = PendingRating(
                            from_user_vk_id=driver.vk_id,
                            to_user_id=passenger.id,
                            trip_id=booking.id,
                            target_name=f"{passenger.first_name} {passenger.last_name}"
                        )
                        session.add(pending)
                        await session.commit()
                        
                        # Отправляем запрос оценки водителю
                        try:
                            keyboard = Keyboard(inline=True)
                            keyboard.add(Text("1⭐"), KeyboardButtonColor.SECONDARY)
                            keyboard.add(Text("2⭐"), KeyboardButtonColor.SECONDARY)
                            keyboard.add(Text("3⭐"), KeyboardButtonColor.SECONDARY)
                            keyboard.add(Text("4⭐"), KeyboardButtonColor.SECONDARY)
                            keyboard.add(Text("5⭐"), KeyboardButtonColor.SECONDARY)
                            
                            await api.messages.send(
                                peer_ids=str(driver.vk_id),
                                message=f"⭐ Оцените поездку с {passenger.first_name} {passenger.last_name} (от 1 до 5):",
                                keyboard=keyboard.get_json(),
                                random_id=0
                            )
                            logger.info(f"Rating request sent to driver {driver.vk_id} for passenger {passenger.id}")
                        except Exception as e:
                            logger.error(f"Failed to send rating request to driver: {e}")
            
            for booking in accepted_bookings:
                passenger = await session.get(User, booking.passenger_id)
                if passenger and driver:
                    # Сохраняем PendingRating для БД
                    pending = PendingRating(
                        from_user_vk_id=passenger.vk_id,
                        to_user_id=driver.id,
                        trip_id=booking.id,
                        target_name=f"{driver.first_name} {driver.last_name}"
                    )
                    session.add(pending)
                    await session.commit()
                    
                    # Отправляем запрос оценки пассажиру
                    try:
                        keyboard = Keyboard(inline=True)
                        keyboard.add(Text("1⭐"), KeyboardButtonColor.SECONDARY)
                        keyboard.add(Text("2⭐"), KeyboardButtonColor.SECONDARY)
                        keyboard.add(Text("3⭐"), KeyboardButtonColor.SECONDARY)
                        keyboard.add(Text("4⭐"), KeyboardButtonColor.SECONDARY)
                        keyboard.add(Text("5⭐"), KeyboardButtonColor.SECONDARY)
                        
                        await api.messages.send(
                            peer_ids=str(passenger.vk_id),
                            message=f"⭐ Оцените поездку с {driver.first_name} {driver.last_name} (от 1 до 5):",
                            keyboard=keyboard.get_json(),
                            random_id=0
                        )
                        logger.info(f"Rating request sent to passenger {passenger.vk_id} for driver {driver.id}")
                    except Exception as e:
                        logger.error(f"Failed to send rating request to passenger: {e}")
        
        logger.info(f"Scheduler: completed {len(trips_to_complete)} trips")
