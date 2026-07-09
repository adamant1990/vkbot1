from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import Trip, User, Booking, BookingStatus, Subscription, Rating
from sqlalchemy import select, and_
from datetime import datetime, timezone, timedelta
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_user_by_vk_id, get_user_by_id, get_trip_by_id, get_booking_by_id, update_user_rating
from loguru import logger

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
    """Отменяет бронирование с проверкой времени и штрафом"""
    booking_id = int(message.text.split()[-1])
    
    async for session in get_session():
        booking = await get_booking_by_id(session, booking_id)
        if not booking or booking.status not in [BookingStatus.pending, BookingStatus.accepted]:
            await message.answer("❌ Бронирование не найдено или уже отменено")
            return
        
        user = await get_user_by_vk_id(session, message.from_id)
        if booking.passenger_id != user.id:
            await message.answer("❌ Это не ваше бронирование")
            return
        
        trip = await get_trip_by_id(session, booking.trip_id)
        driver = await get_user_by_id(session, trip.driver_id)
        
        now = datetime.now(timezone.utc)
        time_until_departure = trip.departure_time - now
        
        if time_until_departure < timedelta(hours=2):
            # Блокировка на 24 часа
            user.banned_until = now + timedelta(hours=24)
            
            # Добавляем оценку 1 как штраф
            penalty = Rating(
                booking_id=booking.id,
                from_user_id=user.id,
                to_user_id=user.id,
                value=1
            )
            session.add(penalty)
            
            # Пересчитываем рейтинг
            await update_user_rating(session, user.id)
            
            await message.answer(
                "⚠️ Отмена менее чем за 2 часа!\n"
                "🚫 Вы заблокированы на 24 часа.\n"
                "⭐ Ваш рейтинг снижен."
            )
        
        if booking.status == BookingStatus.accepted:
            trip.seats_available += 1
        
        booking.status = BookingStatus.cancelled
        await session.commit()
        
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
        
        await message.answer("✅ Бронирование отменено", keyboard=main_menu_keyboard())
        logger.info(f"Booking {booking_id} cancelled by passenger")

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
