from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import Trip, TripStatus, User, Booking, BookingStatus, Subscription
from sqlalchemy import select, and_
from datetime import datetime, timezone, timedelta
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_user_by_vk_id, get_user_by_id, get_trip_by_id, apply_rating_penalty
from loguru import logger
from storage import ctx

async def my_bookings_menu_handler(message: Message):
    """Показывает меню раздела бронирований"""
    keyboard = Keyboard(inline=False)
    keyboard.add(Text("📌 Мои бронирования"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🔔 Активные подписки"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
    
    await message.answer("🧑 ЛК Пассажира:", keyboard=keyboard.get_json())

async def my_bookings_handler(message: Message):
    """Показывает активные бронирования пассажира"""
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        
        result = await session.execute(
            select(Booking, Trip).join(
                Trip, Booking.trip_id == Trip.id
            ).where(
                and_(
                    Booking.passenger_id == user.id,
                    Booking.status.in_([BookingStatus.pending, BookingStatus.accepted])
                )
            ).order_by(Trip.departure_time)
        )
        
        bookings = result.all()
        
        if not bookings:
            await message.answer("У вас нет активных бронирований", keyboard=main_menu_keyboard())
            return
        
        for booking, trip in bookings:
            status_text = {
                BookingStatus.pending: "⏳ Ожидает подтверждения",
                BookingStatus.accepted: "✅ Подтверждено"
            }.get(booking.status, booking.status.value)
            
            booking_info = (
                f"🚗 Бронь #{booking.id} - {status_text}\n"
                f"📍 {trip.route_from} → {trip.route_to}\n"
                f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 Цена: {trip.price}₽\n"
            )
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"❌ Отменить {booking.id}"), KeyboardButtonColor.NEGATIVE)
            
            await message.answer(booking_info, keyboard=keyboard.get_json())

async def cancel_booking_handler(message: Message):
    """Первый шаг отмены: проверяет владельца брони и время до поездки."""
    try:
        booking_id = int(message.text.split()[-1])
    except (ValueError, IndexError):
        await message.answer("❌ Не удалось определить номер бронирования")
        return

    async for session in get_session():
        booking_result = await session.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        )
        booking = booking_result.scalar_one_or_none()
        if not booking or booking.status not in [BookingStatus.pending, BookingStatus.accepted]:
            await message.answer("❌ Бронирование не найдено или уже обработано")
            return

        user = await get_user_by_vk_id(session, message.from_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        if booking.passenger_id != user.id:
            await message.answer("❌ Это не ваше бронирование")
            return

        trip = await get_trip_by_id(session, booking.trip_id)
        if not trip or trip.status != TripStatus.active:
            await message.answer("❌ Эта поездка уже недоступна для отмены")
            return

        now = datetime.now(timezone.utc)
        departure_time = trip.departure_time
        if departure_time.tzinfo is None:
            departure_time = departure_time.replace(tzinfo=timezone.utc)
        time_until_departure = departure_time - now

        if time_until_departure <= timedelta(0):
            await message.answer("❌ Время отправления уже наступило")
            return

        if time_until_departure < timedelta(hours=2):
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"⚠️ Да, отменить {booking.id}"), KeyboardButtonColor.NEGATIVE)
            keyboard.add(Text("❌ Нет"), KeyboardButtonColor.SECONDARY)

            await message.answer(
                "⚠️ До поездки менее 2 часов. При подтверждении отмены:
"
                "• Рейтинг будет снижен на 1 балл
"
                "• Бронирование будет недоступно в течение 24 часов

"
                "Вы уверены, что хотите отменить бронирование?",
                keyboard=keyboard.get_json()
            )
            return

        await perform_cancel(session, booking, trip, user, message)


async def confirm_cancel_booking(message: Message):
    """Подтверждает позднюю отмену, повторно проверяя все условия."""
    try:
        booking_id = int(message.text.split()[-1])
    except (ValueError, IndexError):
        await message.answer("❌ Не удалось определить номер бронирования")
        return

    async for session in get_session():
        result = await session.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
        )
        booking = result.scalar_one_or_none()
        if not booking or booking.status not in [BookingStatus.pending, BookingStatus.accepted]:
            await message.answer("❌ Бронирование уже обработано или не найдено")
            return

        user = await get_user_by_vk_id(session, message.from_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        if booking.passenger_id != user.id:
            await message.answer("❌ Это не ваше бронирование")
            return

        trip = await get_trip_by_id(session, booking.trip_id)
        if not trip or trip.status != TripStatus.active:
            await message.answer("❌ Эта поездка уже недоступна для отмены")
            return

        now = datetime.now(timezone.utc)
        departure_time = trip.departure_time
        if departure_time.tzinfo is None:
            departure_time = departure_time.replace(tzinfo=timezone.utc)
        time_until_departure = departure_time - now

        if time_until_departure <= timedelta(0):
            await message.answer("❌ Время отправления уже наступило")
            return

        penalty_applied = False
        if time_until_departure < timedelta(hours=2):
            penalty_applied = await apply_rating_penalty(session, user.id, booking.id)
            user.banned_until = now + timedelta(hours=24)

        await perform_cancel(
            session, booking, trip, user, message,
            penalty_applied=penalty_applied,
            blocked_until=user.banned_until if time_until_departure < timedelta(hours=2) else None
        )


async def perform_cancel(session, booking, trip, user, message, penalty_applied=False, blocked_until=None):
    """Атомарно отменяет бронь и возвращает место; уведомления отправляет после COMMIT."""
    if booking.status == BookingStatus.accepted:
        trip.seats_available = min(trip.seats_total, trip.seats_available + 1)

    booking.status = BookingStatus.cancelled
    await session.commit()

    driver = await get_user_by_id(session, trip.driver_id)
    if driver:
        from handlers.menu import send_notification
        await send_notification(
            driver.vk_id,
            f"❌ Пассажир отменил бронирование.\n\n"
            f"🚗 {trip.route_from} → {trip.route_to}\n"
            f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"👤 Пассажир: {user.first_name} {user.last_name}\n"
            f"💺 Свободных мест: {trip.seats_available}/{trip.seats_total}"
        )

    if penalty_applied:
        until_text = blocked_until.strftime('%d.%m.%Y %H:%M') if blocked_until else "через 24 часа"
        await message.answer(
            "✅ Бронирование отменено. Применён штраф:\n"
            "• Рейтинг снижен на 1 балл\n"
            f"• Блокировка бронирования до {until_text} (МСК)",
            keyboard=main_menu_keyboard()
        )
    else:
        await message.answer("✅ Бронирование отменено", keyboard=main_menu_keyboard())

    logger.info(f"Booking {booking.id} cancelled by passenger (penalty={penalty_applied})")


async def subscriptions_handler(message: Message):
    """Показывает активные подписки пассажира"""
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id
            ).order_by(Subscription.date)
        )
        
        subscriptions = result.scalars().all()
        
        if not subscriptions:
            await message.answer("У вас нет активных подписок", keyboard=main_menu_keyboard())
            return
        
        for sub in subscriptions:
            date_str = sub.date.strftime('%d.%m.%Y') if sub.date else "Любая дата"
            
            sub_info = (
                f"🔔 Подписка #{sub.id}\n"
                f"📍 {sub.route_from} → {sub.route_to}\n"
                f"📅 {date_str}\n"
            )
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"🔕 Отписаться {sub.id}"), KeyboardButtonColor.NEGATIVE)
            
            await message.answer(sub_info, keyboard=keyboard.get_json())

async def unsubscribe_handler(message: Message):
    """Отписывает от уведомлений"""
    sub_id = int(message.text.split()[-1])
    
    async for session in get_session():
        subscription = await session.get(Subscription, sub_id)
        if subscription:
            await session.delete(subscription)
            await session.commit()
            await message.answer("✅ Подписка удалена", keyboard=main_menu_keyboard())
        else:
            await message.answer("❌ Подписка не найдена")
