import datetime

from sqlalchemy import and_, select, update
from db import async_session_maker
from models import (
    Booking,
    BookingStatus,
    PendingRating,
    Rating,
    Subscription,
    Trip,
    TripStatus,
    User,
)
from loguru import logger
from vkbottle import API, Keyboard, Text, KeyboardButtonColor
from config import settings


def _rating_keyboard(pending_id: int) -> str:
    """Кнопки содержат ID конкретного запроса, поэтому оценки не путаются."""
    keyboard = Keyboard(inline=True)
    for value in range(1, 6):
        keyboard.add(
            Text(
                f"{value}⭐",
                payload={"pending_rating_id": pending_id, "rating": value},
            ),
            KeyboardButtonColor.SECONDARY,
        )
    return keyboard.get_json()


async def _deliver_pending_rating_requests(api: API) -> None:
    """Доставляет неотправленные запросы; неудачные попытки остаются в очереди."""
    async with async_session_maker() as session:
        result = await session.execute(
            select(PendingRating, User.vk_id)
            .join(User, User.id == PendingRating.from_user_id)
            .where(PendingRating.sent_at.is_(None))
            .order_by(PendingRating.id)
            .limit(100)
        )
        pending_rows = [
            (
                pending.id,
                vk_id,
                pending.target_name or "участника поездки",
            )
            for pending, vk_id in result.all()
        ]

    for pending_id, sender_vk_id, target_name in pending_rows:
        try:
            await api.messages.send(
                peer_ids=str(sender_vk_id),
                message=f"⭐ Оцените поездку с {target_name} (от 1 до 5):",
                keyboard=_rating_keyboard(pending_id),
                # Повторная отправка после сбоя использует тот же VK random_id.
                random_id=pending_id,
            )
        except Exception as exc:
            async with async_session_maker() as session:
                await session.execute(
                    update(PendingRating)
                    .where(
                        PendingRating.id == pending_id,
                        PendingRating.sent_at.is_(None),
                    )
                    .values(
                        attempts=PendingRating.attempts + 1,
                        last_error=str(exc)[:2000],
                    )
                )
                await session.commit()
            logger.error(
                f"Failed to deliver rating request {pending_id} "
                f"to VK user {sender_vk_id}: {exc}"
            )
        else:
            async with async_session_maker() as session:
                await session.execute(
                    update(PendingRating)
                    .where(
                        PendingRating.id == pending_id,
                        PendingRating.sent_at.is_(None),
                    )
                    .values(
                        sent_at=datetime.datetime.now(datetime.timezone.utc),
                        attempts=PendingRating.attempts + 1,
                        last_error=None,
                    )
                )
                await session.commit()
            logger.info(
                f"Rating request {pending_id} sent to VK user {sender_vk_id}"
            )


async def complete_trips_and_request_ratings():
    """
    Завершает поездки и создаёт запросы оценок одной транзакцией.
    Отправка VK выполняется после commit и может безопасно повторяться.
    """
    logger.info("Scheduler: checking trips to complete...")
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=24)

    async with async_session_maker() as session:
        # Удаляются только просроченные подписки. История поездок,
        # бронирований и оценок физически не удаляется.
        old_subs_result = await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.date.isnot(None),
                    Subscription.date
                    < (now - datetime.timedelta(hours=24)).replace(tzinfo=None),
                )
            )
        )
        old_subs = old_subs_result.scalars().all()
        for subscription in old_subs:
            await session.delete(subscription)

        # Старые незавершённые бронирования меняют статус, но остаются в истории.
        old_bookings_result = await session.execute(
            select(Booking)
            .join(Trip, Booking.trip_id == Trip.id)
            .where(
                and_(
                    Trip.status.in_([TripStatus.completed, TripStatus.cancelled]),
                    Trip.departure_time < cutoff,
                    Booking.status.in_(
                        [BookingStatus.pending, BookingStatus.accepted]
                    ),
                )
            )
        )
        old_bookings = old_bookings_result.scalars().all()
        for booking in old_bookings:
            booking.status = BookingStatus.cancelled
            logger.info(f"Scheduler: auto-cancelled old booking {booking.id}")

        result = await session.execute(
            select(Trip).where(
                and_(
                    Trip.status == TripStatus.active,
                    Trip.departure_time <= cutoff,
                )
            )
        )
        trips_to_complete = result.scalars().all()

        for trip in trips_to_complete:
            bookings_result = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip.id,
                        Booking.status == BookingStatus.accepted,
                    )
                )
            )
            accepted_bookings = bookings_result.scalars().all()
            driver = await session.get(User, trip.driver_id)

            if driver:
                for booking in accepted_bookings:
                    passenger = await session.get(User, booking.passenger_id)
                    if not passenger:
                        logger.warning(
                            f"Booking {booking.id}: passenger {booking.passenger_id} not found"
                        )
                        continue

                    # Оценки создаются в обе стороны, каждая привязана к Booking.id.
                    for sender, target in (
                        (driver, passenger),
                        (passenger, driver),
                    ):
                        existing_rating = await session.execute(
                            select(Rating.id).where(
                                Rating.booking_id == booking.id,
                                Rating.from_user_id == sender.id,
                            ).limit(1)
                        )
                        if existing_rating.scalar_one_or_none() is not None:
                            continue

                        existing_pending = await session.execute(
                            select(PendingRating.id).where(
                                PendingRating.booking_id == booking.id,
                                PendingRating.from_user_id == sender.id,
                            ).limit(1)
                        )
                        if existing_pending.scalar_one_or_none() is not None:
                            continue

                        session.add(
                            PendingRating(
                                booking_id=booking.id,
                                from_user_id=sender.id,
                                to_user_id=target.id,
                                target_name=(
                                    f"{target.first_name or ''} "
                                    f"{target.last_name or ''}"
                                ).strip(),
                            )
                        )

            trip.status = TripStatus.completed
            logger.info(f"Trip {trip.id} marked as completed")

        # Один commit для статусов поездок и созданных запросов оценок.
        await session.commit()

    if trips_to_complete:
        logger.info(f"Scheduler: completed {len(trips_to_complete)} trips")

    # Доставка идёт после commit: сбой VK не откатывает завершение поездок.
    api = API(token=settings.VK_GROUP_TOKEN)
    await _deliver_pending_rating_requests(api)
