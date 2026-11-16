import datetime
from sqlalchemy import select, and_
from db import async_session_maker
from models import Trip, TripStatus, Booking, BookingStatus, User, Subscription, PendingRating
from loguru import logger
from vkbottle import API, Keyboard, Text, KeyboardButtonColor
from config import settings

async def complete_trips_and_request_ratings():
    """Завершает поездки, создаёт запросы оценок и очищает только безопасные временные данные."""
    logger.info("Scheduler: checking trips to complete...")
    notifications = []

    async with async_session_maker() as session:
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(hours=24)

        # Удаляем только старые подписки. Историю поездок, броней и оценок сохраняем.
        old_subs_result = await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.date.isnot(None),
                    Subscription.date < (now - datetime.timedelta(hours=24)).replace(tzinfo=None)
                )
            )
        )
        old_subs = old_subs_result.scalars().all()
        for sub in old_subs:
            await session.delete(sub)
        if old_subs:
            logger.info(f"Scheduler: cleaned {len(old_subs)} old subscriptions")

        # Старые незавершённые заявки закрываем, но сами записи броней не удаляем:
        # на них могут ссылаться сохранённые оценки.
        old_bookings_result = await session.execute(
            select(Booking).join(
                Trip, Booking.trip_id == Trip.id
            ).where(
                and_(
                    Trip.status.in_([TripStatus.completed, TripStatus.cancelled]),
                    Trip.departure_time < cutoff,
                    Booking.status.in_([BookingStatus.pending, BookingStatus.accepted])
                )
            )
        )
        old_bookings = old_bookings_result.scalars().all()
        for booking in old_bookings:
            booking.status = BookingStatus.cancelled
            logger.info(f"Scheduler: auto-cancelled old booking {booking.id}")

        # Не удаляем старые поездки и брони физически: ratings.booking_id имеет FK
        # на bookings, а pending_ratings.trip_id — FK на trips.

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
            await session.commit()
            logger.info("Scheduler: no trips to complete")
            return

        logger.info(f"Scheduler: completing {len(trips_to_complete)} trips")

        for trip in trips_to_complete:
            trip.status = TripStatus.completed
            logger.info(f"Trip {trip.id} marked as completed")

            bookings_result = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip.id,
                        Booking.status == BookingStatus.accepted
                    )
                ).order_by(Booking.id)
            )
            accepted_bookings = bookings_result.scalars().all()
            driver = await session.get(User, trip.driver_id)

            if not driver:
                continue

            for booking in accepted_bookings:
                passenger = await session.get(User, booking.passenger_id)
                if not passenger:
                    continue

                # В PendingRating.trip_id хранится именно ID поездки, как требует FK.
                rating_targets = [
                    (driver.vk_id, passenger.id, f"{passenger.first_name} {passenger.last_name}",
                     driver.vk_id, f"Оцените поездку с {passenger.first_name} {passenger.last_name}"),
                    (passenger.vk_id, driver.id, f"{driver.first_name} {driver.last_name}",
                     passenger.vk_id, f"Оцените поездку с {driver.first_name} {driver.last_name}")
                ]

                for from_vk_id, to_user_id, target_name, recipient_vk_id, prompt in rating_targets:
                    existing = await session.execute(
                        select(PendingRating.id).where(
                            PendingRating.from_user_vk_id == from_vk_id,
                            PendingRating.to_user_id == to_user_id,
                            PendingRating.trip_id == trip.id
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none() is not None:
                        continue

                    session.add(PendingRating(
                        from_user_vk_id=from_vk_id,
                        to_user_id=to_user_id,
                        trip_id=trip.id,
                        target_name=target_name
                    ))
                    notifications.append((recipient_vk_id, prompt, trip.id, to_user_id))

        # Один COMMIT фиксирует статусы поездок и все ожидающие оценки,
        # даже если у завершённой поездки не было подтверждённых броней.
        await session.commit()

    api = API(token=settings.VK_GROUP_TOKEN)
    for recipient_vk_id, prompt, trip_id, target_id in notifications:
        try:
            keyboard = Keyboard(inline=True)
            keyboard.add(Text("1⭐"), KeyboardButtonColor.SECONDARY)
            keyboard.add(Text("2⭐"), KeyboardButtonColor.SECONDARY)
            keyboard.add(Text("3⭐"), KeyboardButtonColor.SECONDARY)
            keyboard.add(Text("4⭐"), KeyboardButtonColor.SECONDARY)
            keyboard.add(Text("5⭐"), KeyboardButtonColor.SECONDARY)

            await api.messages.send(
                peer_ids=str(recipient_vk_id),
                message=f"⭐ {prompt} (от 1 до 5):",
                keyboard=keyboard.get_json(),
                random_id=0
            )
            logger.info(
                f"Rating request sent to {recipient_vk_id} for trip {trip_id}, target {target_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send rating request to {recipient_vk_id}: {e}")

    logger.info(f"Scheduler: completed {len(trips_to_complete)} trips")


