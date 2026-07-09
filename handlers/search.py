from vkbottle import BaseStateGroup
from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import Trip, TripStatus, User, Booking, BookingStatus, Subscription
from sqlalchemy import select, and_
from loguru import logger
from datetime import datetime, timedelta, timezone
from vkbottle import Keyboard, Text, KeyboardButtonColor, API
from utils.db_utils import get_user_by_vk_id, get_user_by_id, get_setting
from storage import ctx
from config import settings

class SearchState(BaseStateGroup):
    WAITING_ROUTE = 1
    WAITING_DATE = 2
    WAITING_MANUAL_DATE = 3
    WAITING_SORT = 4

SEARCH_RESULTS_PER_PAGE = 3

def safe_delete(key: str):
    """Безопасное удаление ключа из хранилища"""
    try:
        ctx.delete(key)
    except KeyError:
        pass

def parse_route(text: str):
    """Разбирает текст на города отправления и назначения"""
    text = text.replace('—', '-').replace('–', '-')
    text = ' '.join(text.split())
    
    route_from = None
    route_to = None
    
    if '-' in text:
        parts = text.split('-', 1)
        route_from = parts[0].strip()
        route_to = parts[1].strip() if len(parts) > 1 else None
    
    if not route_from or not route_to:
        parts = text.split()
        if len(parts) >= 2:
            route_from = parts[0]
            route_to = parts[-1]
    
    return route_from, route_to

# ============ Календарь ============

def get_next_days():
    """Возвращает список из 3 ближайших дней"""
    today = datetime.now()
    days = []
    
    labels = [
        f"Сегодня ({today.strftime('%d.%m')})",
        f"Завтра ({(today + timedelta(days=1)).strftime('%d.%m')})",
        f"Послезавтра ({(today + timedelta(days=2)).strftime('%d.%m')})",
    ]
    
    for i, label in enumerate(labels):
        day = today + timedelta(days=i)
        days.append({
            'date': day.strftime('%d.%m.%Y'),
            'label': label
        })
    
    return days

def build_calendar_keyboard():
    """Создаёт клавиатуру с 3 днями + кнопка другой даты"""
    keyboard = Keyboard(inline=False)
    days = get_next_days()
    
    keyboard.add(Text(days[0]['label']), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text(days[1]['label']), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    
    keyboard.add(Text(days[2]['label']), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("📆 Другая дата"), KeyboardButtonColor.SECONDARY)
    keyboard.row()
    
    keyboard.add(Text("🔙 Отмена"), KeyboardButtonColor.SECONDARY)
    
    return keyboard

def parse_calendar_date(text: str):
    """Пытается извлечь дату из текста кнопки календаря"""
    try:
        parts = text.split('(')
        if len(parts) > 1:
            date_str = parts[1].replace(')', '').strip()
            today = datetime.now()
            parsed = datetime.strptime(f"{date_str}.{today.year}", '%d.%m.%Y')
            if parsed.date() < today.date():
                parsed = parsed.replace(year=today.year + 1)
            return parsed
    except:
        pass
    return None

async def search_trip_handler(message: Message):
    """Начинает поиск поездки"""
    user_id = message.from_id
    
    safe_delete(f"search_results_{user_id}")
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь! Отправьте 'Начать'")
            return
        
        if user.is_banned:
            await message.answer("❌ Ваш аккаунт заблокирован")
            return
        
        if user.banned_until and user.banned_until > datetime.now(timezone.utc):
            await message.answer(
                f"🚫 Вы временно заблокированы до {user.banned_until.strftime('%d.%m.%Y %H:%M')} (МСК) "
                f"из-за отмены бронирования менее чем за 2 часа."
            )
            return
    
    await message.answer(
        "🔍 Введите маршрут в формате: ГородОтправления-ГородНазначения\n"
        "Например: Туймазы-Уфа или Туймазы Уфа"
    )
    ctx.set(f"search_state_{user_id}", SearchState.WAITING_ROUTE)

async def process_search_route(message: Message):
    """Обрабатывает маршрут для поиска"""
    user_id = message.from_id
    route_from, route_to = parse_route(message.text.strip())
    
    if not route_from or not route_to:
        await message.answer(
            "❌ Не удалось определить маршрут.\n"
            "Используйте форматы:\n"
            "• Город1-Город2 (например: Уфа-Туймазы)\n"
            "• Город1 Город2 (например: Уфа Туймазы)"
        )
        return
    
    ctx.set(f"search_from_{user_id}", route_from)
    ctx.set(f"search_to_{user_id}", route_to)
    
    keyboard = build_calendar_keyboard()
    await message.answer(
        f"🔍 Маршрут: {route_from} → {route_to}\n\n"
        "📅 Выберите дату поездки:",
        keyboard=keyboard.get_json()
    )
    ctx.set(f"search_state_{user_id}", SearchState.WAITING_DATE)

async def process_search_calendar_date(message: Message):
    """Обрабатывает выбор даты из календаря при поиске"""
    user_id = message.from_id
    text = message.text.strip()
    
    if text == "📆 Другая дата":
        await message.answer(
            "📅 Введите дату в формате ДД.ММ.ГГГГ:\n"
            "Например: 25.12.2024"
        )
        ctx.set(f"search_state_{user_id}", SearchState.WAITING_MANUAL_DATE)
        return
    
    if text == "🔙 Отмена":
        safe_delete(f"search_state_{user_id}")
        from handlers.menu import send_main_menu
        await send_main_menu(message)
        return
    
    selected_date = parse_calendar_date(text)
    if selected_date:
        ctx.set(f"search_date_{user_id}", selected_date)
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("📅 По дате"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("💰 По цене"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("⭐ По рейтингу"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"✅ Дата: {selected_date.strftime('%d.%m.%Y')}\n\n"
            "Выберите сортировку:",
            keyboard=keyboard.get_json()
        )
        ctx.set(f"search_state_{user_id}", SearchState.WAITING_SORT)
    else:
        await process_search_manual_date(message)

async def process_search_manual_date(message: Message):
    """Обрабатывает ручной ввод даты при поиске"""
    user_id = message.from_id
    
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
        if date.date() < datetime.now().date():
            await message.answer("❌ Дата не может быть в прошлом")
            return
        
        ctx.set(f"search_date_{user_id}", date)
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("📅 По дате"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("💰 По цене"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("⭐ По рейтингу"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"✅ Дата: {date.strftime('%d.%m.%Y')}\n\n"
            "Выберите сортировку:",
            keyboard=keyboard.get_json()
        )
        ctx.set(f"search_state_{user_id}", SearchState.WAITING_SORT)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

async def process_sort_and_search(message: Message):
    """Выполняет поиск с выбранной сортировкой, включая промежуточные города"""
    user_id = message.from_id
    sort_text = message.text.strip()
    
    route_from = ctx.get(f"search_from_{user_id}")
    route_to = ctx.get(f"search_to_{user_id}")
    search_date = ctx.get(f"search_date_{user_id}")
    
    if not all([route_from, route_to, search_date]):
        await message.answer("❌ Произошла ошибка. Начните поиск заново.")
        safe_delete(f"search_state_{user_id}")
        safe_delete(f"search_results_{user_id}")
        return
    
    await message.answer("🔍 Ищу подходящие поездки, включая промежуточные города...")
    
    async for session in get_session():
        date_start = search_date.replace(hour=0, minute=0, second=0)
        date_end = search_date.replace(hour=23, minute=59, second=59)
        
        query = select(Trip, User).join(
            User, Trip.driver_id == User.id
        ).where(
            and_(
                Trip.status == TripStatus.active,
                Trip.departure_time >= date_start,
                Trip.departure_time <= date_end,
                Trip.seats_available > 0
            )
        )
        
        if "цене" in sort_text.lower():
            query = query.order_by(Trip.price)
        elif "рейтинг" in sort_text.lower():
            query = query.order_by(User.rating.desc())
        else:
            query = query.order_by(Trip.departure_time)
        
        result = await session.execute(query)
        all_trips = result.all()
        
        max_angle_str = await get_setting(session, "max_angle", "110")
        max_angle = int(max_angle_str)
        
        matching_trips = []
        
        from utils.yandex_routing import check_intermediate_route
        
        for trip, driver in all_trips:
            if (trip.route_from.lower() == route_from.lower() and 
                trip.route_to.lower() == route_to.lower()):
                matching_trips.append((trip, driver))
            else:
                is_on_route = await check_intermediate_route(
                    route_from, route_to,
                    trip.route_from, trip.route_to,
                    max_detour_km=80,
                    max_angle=max_angle
                )
                if is_on_route:
                    matching_trips.append((trip, driver))
        
        if not matching_trips:
            keyboard = Keyboard(inline=False)
            keyboard.add(Text("🔔 Подписаться на маршрут"), KeyboardButtonColor.PRIMARY)
            keyboard.row()
            keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
            
            await message.answer(
                "😔 Подходящих поездок не найдено.\n"
                "Хотите подписаться на уведомления?",
                keyboard=keyboard.get_json()
            )
            safe_delete(f"search_state_{user_id}")
            return
        
        ctx.set(f"search_results_{user_id}", {
            'trips': matching_trips,
            'page': 0
        })
        safe_delete(f"search_state_{user_id}")
        
        await show_search_page(message, user_id, 0)

async def show_search_page(message: Message, user_id: int, page: int):
    """Показывает страницу результатов поиска"""
    search_data = ctx.get(f"search_results_{user_id}")
    
    if not search_data:
        await message.answer("❌ Результаты поиска устарели. Начните заново.")
        return
    
    trips = search_data['trips']
    total_pages = (len(trips) - 1) // SEARCH_RESULTS_PER_PAGE + 1
    
    start_idx = page * SEARCH_RESULTS_PER_PAGE
    end_idx = min(start_idx + SEARCH_RESULTS_PER_PAGE, len(trips))
    
    if start_idx >= len(trips):
        await message.answer("Больше результатов нет")
        return
    
    for i in range(start_idx, end_idx):
        trip, driver = trips[i]
        
        rating_str = f"{driver.rating:.1f}⭐" if driver.rating else "Нет оценок"
        
        trip_info = (
            f"🚗 Поездка #{trip.id}\n"
            f"👤 Водитель: {driver.first_name} {driver.last_name}\n"
            f"⭐ Рейтинг: {rating_str}\n"
            f"📍 Маршрут: {trip.route_from} → {trip.route_to}\n"
            f"📅 Дата: {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"💺 Свободно мест: {trip.seats_available}/{trip.seats_total}\n"
            f"💰 Цена: {trip.price}₽\n"
        )
        if trip.comment:
            trip_info += f"💬 Комментарий: {trip.comment}\n"
        
        keyboard = Keyboard(inline=True)
        keyboard.add(Text(f"💬 Обсудить {trip.id}"), KeyboardButtonColor.PRIMARY)
        keyboard.add(Text(f"✅ Бронировать {trip.id}"), KeyboardButtonColor.POSITIVE)
        
        await message.answer(trip_info, keyboard=keyboard.get_json())
    
    if total_pages > 1:
        keyboard = Keyboard(inline=False)
        if page > 0:
            keyboard.add(Text("⬅ Назад"), KeyboardButtonColor.PRIMARY)
            keyboard.row()
        if page < total_pages - 1:
            keyboard.add(Text("Вперёд ➡"), KeyboardButtonColor.PRIMARY)
            keyboard.row()
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"Страница {page + 1} из {total_pages}",
            keyboard=keyboard.get_json()
        )
    
    search_data['page'] = page
    ctx.set(f"search_results_{user_id}", search_data)

async def handle_search_navigation(message: Message):
    """Обрабатывает навигацию по страницам поиска"""
    user_id = message.from_id
    search_data = ctx.get(f"search_results_{user_id}")
    
    if not search_data:
        return
    
    current_page = search_data['page']
    
    if "Назад" in message.text:
        new_page = max(0, current_page - 1)
    elif "Вперёд" in message.text:
        new_page = current_page + 1
    else:
        return
    
    await show_search_page(message, user_id, new_page)

async def handle_search_action(message: Message):
    """Обрабатывает действия с поездкой"""
    user_id = message.from_id
    text = message.text.strip()
    
    if "Обсудить" in text:
        trip_id = int(text.split()[-1])
        
        async for session in get_session():
            from utils.db_utils import get_trip_by_id
            trip = await get_trip_by_id(session, trip_id)
            if trip:
                driver = await get_user_by_id(session, trip.driver_id)
                
                if driver is None:
                    await message.answer("❌ Водитель не найден")
                    return
                
                current_user = await get_user_by_vk_id(session, user_id)
                if current_user and driver.id == current_user.id:
                    await message.answer(
                        f"👤 Это ваша поездка!\n"
                        f"📍 {trip.route_from} → {trip.route_to}\n"
                        f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"💰 {trip.price}₽\n"
                        f"💺 Свободно: {trip.seats_available} мест\n\n"
                        f"ℹ️ Это ваша собственная поездка."
                    )
                    return
                
                await message.answer(
                    f"👤 Водитель: @id{driver.vk_id}({driver.first_name} {driver.last_name})\n"
                    f"📱 Телефон: {driver.phone or 'не указан'}\n"
                    f"📍 Маршрут: {trip.route_from} → {trip.route_to}\n"
                    f"📅 Дата: {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"💰 Цена: {trip.price}₽\n"
                    f"💺 Свободно: {trip.seats_available} мест\n\n"
                    f"⚠️ ВАЖНО: Для гарантии поездки обязательно забронируйте место "
                    f"через кнопку «Бронировать» после обсуждения деталей с водителем!\n\n"
                    f"💬 Свяжитесь с водителем для уточнения всех деталей поездки."
                )
    
    elif "Бронировать" in text:
        trip_id = int(text.split()[-1])
        
        async for session in get_session():
            user = await get_user_by_vk_id(session, user_id)
            
            # Проверка временной блокировки
            if user.banned_until and user.banned_until > datetime.now(timezone.utc):
                await message.answer(
                    f"🚫 Вы временно заблокированы до {user.banned_until.strftime('%d.%m.%Y %H:%M')} (МСК) "
                    f"из-за отмены бронирования менее чем за 2 часа."
                )
                return
            
            from utils.db_utils import get_trip_by_id
            trip = await get_trip_by_id(session, trip_id)
            driver = await get_user_by_id(session, trip.driver_id)
            
            if not trip or trip.status != TripStatus.active:
                await message.answer("❌ Поездка недоступна")
                return
            
            if trip.driver_id == user.id:
                await message.answer("❌ Вы не можете забронировать свою поездку")
                return
            
            if trip.seats_available <= 0:
                await message.answer("❌ Нет свободных мест")
                return
            
            existing = await session.execute(
                select(Booking).where(
                    and_(
                        Booking.trip_id == trip_id,
                        Booking.passenger_id == user.id,
                        Booking.status.in_([BookingStatus.pending, BookingStatus.accepted])
                    )
                )
            )
            if existing.scalar():
                await message.answer("❌ У вас уже есть активная заявка на эту поездку")
                return
            
            booking = Booking(
                trip_id=trip_id,
                passenger_id=user.id,
                status=BookingStatus.pending
            )
            session.add(booking)
            await session.commit()
            
            if driver:
                try:
                    api = API(token=settings.VK_GROUP_TOKEN)
                    keyboard = Keyboard(inline=True)
                    keyboard.add(Text(f"✅ Принять {booking.id}"), KeyboardButtonColor.POSITIVE)
                    keyboard.add(Text(f"❌ Отклонить {booking.id}"), KeyboardButtonColor.NEGATIVE)
                    
                    await api.messages.send(
                        peer_ids=str(driver.vk_id),
                        message=(
                            f"📩 Новое бронирование!\n\n"
                            f"🚗 Поездка: {trip.route_from} → {trip.route_to}\n"
                            f"📅 {trip.departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"👤 Пассажир: {user.first_name} {user.last_name}\n"
                            f"💰 Цена: {trip.price}₽\n\n"
                            f"Выберите действие:"
                        ),
                        keyboard=keyboard.get_json(),
                        random_id=0
                    )
                    logger.info(f"Booking notification with buttons sent to driver {driver.vk_id}")
                except Exception as e:
                    logger.error(f"Failed to send booking notification to driver: {e}")
            
            safe_delete(f"search_results_{user_id}")
            
            await message.answer(
                "✅ Заявка на бронирование отправлена!\n"
                "Водитель получил уведомление с кнопками для подтверждения.",
                keyboard=main_menu_keyboard()
            )
            logger.info(f"Booking created: trip={trip_id}, passenger={user_id}")
    
    elif "Подписаться" in text:
        route_from = ctx.get(f"search_from_{user_id}")
        route_to = ctx.get(f"search_to_{user_id}")
        search_date = ctx.get(f"search_date_{user_id}")
        
        if not route_from or not route_to:
            await message.answer("❌ Данные поиска устарели. Начните заново.")
            return
        
        async for session in get_session():
            user = await get_user_by_vk_id(session, user_id)
            
            subscription = Subscription(
                user_id=user.id,
                route_from=route_from,
                route_to=route_to,
                date=search_date
            )
            session.ad
