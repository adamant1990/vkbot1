from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import Trip, TripStatus, User, Booking, BookingStatus
from sqlalchemy import select, and_
from loguru import logger
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_user_by_vk_id, get_trip_by_id, get_booking_by_id, get_user_by_id

async def my_trips_menu_handler(message: Message):
    """Показывает меню раздела 'Мои поездки'"""
    keyboard = Keyboard(inline=False)
    keyboard.add(Text("🚗 Активные поездки"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("📩 Входящие заявки"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
    
    await message.answer("📋 Мои поездки:", keyboard=keyboard.get_json())

async def active_trips_handler(message: Message):
    """Показывает активные поездки водителя"""
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        result = await session.execute(
            select(Trip).where(
                and_(
                    Trip.driver_id == user.id,
                    Trip.status == TripStatus.active
                )
            ).order_by(Trip.departure_time)
        )
        trips = result.scalars().all()
        
        if not trips:
            await message.answer("У вас нет активных поездок", keyboard=main_menu_keyboard())
            return
        
        for trip in trips:
            bookings_result = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip.id,
                        Booking.status == BookingStatus.accepted
                    )
                )
            )
            confirmed = len(bookings_result.scalars().all())
            
            trip_info = (
                f"🚗 Поездка #{trip.id}\n"
                f"📍 {trip.route_from} → {trip.route_to}\n"
                f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"💺 Свободно: {trip.seats_available}/{trip.seats_total}\n"
                f"✅ Подтверждено: {confirmed}\n"
                f"💰 Цена: {trip.price}₽\n"
            )
            if trip.comment:
                trip_info += f"💬 {trip.comment}\n"
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"🗑 Удалить {trip.id}"), KeyboardButtonColor.NEGATIVE)
            
            await message.answer(trip_info, keyboard=keyboard.get_json())

async def delete_trip_handler(message: Message):
    """Удаляет поездку с проверками"""
    trip_id = int(message.text.split()[-1])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        trip = await get_trip_by_id(session, trip_id)
        
        if not trip or trip.driver_id != user.id:
            await message.answer("❌ Поездка не найдена")
            return
        
        result = await session.execute(
            select(Booking).where(
                and_(
                    Booking.trip_id == trip_id,
                    Booking.status == BookingStatus.accepted
                )
            )
        )
        confirmed_bookings = result.scalars().all()
        
        if confirmed_bookings:
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"✅ Да, удалить {trip_id}"), KeyboardButtonColor.NEGATIVE)
            keyboard.add(Text("❌ Нет"), KeyboardButtonColor.SECONDARY)
            
            await message.answer(
                f"⚠️ У вас {len(confirmed_bookings)} подтвержденных пассажиров! "
                "При отмене поездки ваш рейтинг снизится на 1 балл. Продолжить?",
                keyboard=keyboard.get_json()
            )
            return
        
        await perform_delete_trip(session, trip, message, user)

async def confirm_delete_trip(message: Message):
    """Подтверждает удаление поездки со штрафом"""
    trip_id = int(message.text.split()[-1])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        trip = await get_trip_by_id(session, trip_id)
        
        if trip and trip.driver_id == user.id:
            if user.rating is not None:
                user.rating = max(0, user.rating - 1)
            
            await perform_delete_trip(session, trip, message, user)

async def perform_delete_trip(session, trip, message, driver):
    """Выполняет удаление поездки и уведомляет пассажиров"""
    result = await session.execute(
        select(Booking).where(Booking.trip_id == trip.id)
    )
    bookings = result.scalars().all()
    
    for booking in bookings:
        if booking.status == BookingStatus.accepted:
            passenger = await get_user_by_id(session, booking.passenger_id)
            if passenger:
                from handlers.menu import send_notification
                await send_notification(
                    passenger.vk_id,
                    f"❌ Поездка отменена водителем.\n\n"
                    f"🚗 {trip.route_from} → {trip.route_to}\n"
                    f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"👤 Водитель: {driver.first_name} {driver.last_name}\n\n"
                    f"Попробуйте найти другую поездку в боте."
                )
        
        booking.status = BookingStatus.cancelled
    
    trip.status = TripStatus.cancelled
    await session.commit()
    
    await message.answer("✅ Поездка удалена", keyboard=main_menu_keyboard())
    logger.info(f"Trip {trip.id} deleted by driver")

async def incoming_requests_handler(message: Message):
    """Показывает входящие заявки на бронирование"""
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        
        result = await session.execute(
            select(Trip).where(
                and_(
                    Trip.driver_id == user.id,
                    Trip.status == TripStatus.active
                )
            )
        )
        trips = result.scalars().all()
        
        if not trips:
            await message.answer("У вас нет активных поездок", keyboard=main_menu_keyboard())
            return
        
        trip_ids = [trip.id for trip in trips]
        
        result = await session.execute(
            select(Booking, User, Trip).join(
                User, Booking.passenger_id == User.id
            ).join(
                Trip, Booking.trip_id == Trip.id
            ).where(
                and_(
                    Booking.trip_id.in_(trip_ids),
                    Booking.status == BookingStatus.pending
                )
            ).order_by(Booking.created_at)
        )
        
        bookings = result.all()
        
        if not bookings:
            await message.answer("📩 Входящих заявок нет", keyboard=main_menu_keyboard())
            return
        
        for booking, passenger, trip in bookings:
            passenger_rating = f"{passenger.rating:.1f}⭐" if passenger.rating else "Нет оценок"
            
            request_info = (
                f"📩 Заявка #{booking.id}\n"
                f"👤 Пассажир: {passenger.first_name} {passenger.last_name} ({passenger_rating})\n"
                f"🚗 Поездка: {trip.route_from} → {trip.route_to}\n"
                f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"💰 {trip.price}₽"
            )
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text(f"✅ Принять {booking.id}"), KeyboardButtonColor.POSITIVE)
            keyboard.add(Text(f"❌ Отклонить {booking.id}"), KeyboardButtonColor.NEGATIVE)
            
            await message.answer(request_info, keyboard=keyboard.get_json())

async def handle_booking_response(message: Message):
    """Обрабатывает решение по заявке (принять/отклонить) и уведомляет пассажира"""
    text = message.text.strip()
    parts = text.split()
    
    # Извлекаем booking_id (последнее число)
    booking_id = int(parts[-1])
    
    # Определяем действие по тексту
    if "Принять" in text:
        action = "Принять"
    elif "Отклонить" in text:
        action = "Отклонить"
    else:
        logger.warning(f"Неизвестное действие: {text}")
        return
    
    logger.warning(f"HANDLE_BOOKING: action={action}, booking_id={booking_id}")
    
    async for session in get_session():
        booking = await get_booking_by_id(session, booking_id)
        if not booking or booking.status != BookingStatus.pending:
            await message.answer("❌ Заявка уже обработана")
            return
        
        trip = await get_trip_by_id(session, booking.trip_id)
        user = await get_user_by_vk_id(session, message.from_id)
        passenger = await get_user_by_id(session, booking.passenger_id)
        
        if trip.driver_id != user.id:
            await message.answer("❌ Это не ваша поездка")
            return
        
        if action == "Принять":
            if trip.seats_available <= 0:
                await message.answer("❌ Нет свободных мест")
                return
            
            booking.status = BookingStatus.accepted
            trip.seats_available -= 1
            await session.commit()
            
            if passenger:
                from handlers.menu import send_notification
                await send_notification(
                    passenger.vk_id,
                    f"✅ Ваша заявка принята!\n\n"
                    f"🚗 {trip.route_from} → {trip.route_to}\n"
                    f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"💰 {trip.price}₽\n"
                    f"👤 Водитель: {user.first_name} {user.last_name}\n\n"
                    f"💬 Свяжитесь с водителем для уточнения деталей."
                )
            
            await message.answer("✅ Заявка принята! Пассажир уведомлен.")
            logger.info(f"Booking {booking_id} accepted")
        
        elif action == "Отклонить":
            booking.status = BookingStatus.rejected
            await session.commit()
            
            if passenger:
                from handlers.menu import send_notification
                await send_notification(
                    passenger.vk_id,
                    f"❌ Ваша заявка отклонена.\n\n"
                    f"🚗 {trip.route_from} → {trip.route_to}\n"
                    f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n\n"
                    f"Попробуйте найти другую поездку в боте."
                )
            
            await message.answer("❌ Заявка отклонена. Пассажир уведомлен.")
            logger.info(f"Booking {booking_id} rejected")
