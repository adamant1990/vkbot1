from vkbottle import BaseStateGroup, API
from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import User, Trip, TripStatus, Subscription
from datetime import datetime, timedelta, timezone
from loguru import logger
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_user_by_vk_id, get_user_by_id, get_setting
from config import settings
from sqlalchemy import select, and_
from storage import ctx

class CreateTripState(BaseStateGroup):
    WAITING_ROUTE = 1
    WAITING_DATE = 2
    WAITING_MANUAL_DATE = 3
    WAITING_TIME = 4
    WAITING_SEATS = 5
    WAITING_PRICE = 6
    WAITING_COMMENT = 7
    WAITING_PUBLISH = 8

async def safe_delete_ctx(key: str):
    """Безопасное удаление ключа из контекста"""
    try:
        await ctx.delete(key)
    except Exception:
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

def round_price(price: int) -> int:
    """Округляет цену до десятков: 324 → 320, 326 → 330"""
    return round(price / 10) * 10

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

async def create_trip_handler(message: Message):
    """Начинает создание поездки"""
    user_id = message.from_id
    
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
        "➕ Создание поездки\n\n"
        "Введите маршрут в формате:\n"
        "• Город1-Город2 (например: Уфа-Туймазы)\n"
        "• Город1 Город2 (например: Уфа Туймазы)"
    )
    await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_ROUTE)

async def process_route(message: Message):
    """Обрабатывает введенный маршрут"""
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
    
    await ctx.set(f"trip_from_{user_id}", route_from)
    await ctx.set(f"trip_to_{user_id}", route_to)
    
    keyboard = build_calendar_keyboard()
    await message.answer(
        f"📍 Маршрут: {route_from} → {route_to}\n\n"
        "📅 Выберите дату поездки:",
        keyboard=keyboard.get_json()
    )
    await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_DATE)

async def process_calendar_date(message: Message):
    """Обрабатывает выбор даты из календаря"""
    user_id = message.from_id
    text = message.text.strip()
    
    if text == "📆 Другая дата":
        await message.answer(
            "📅 Введите дату в формате ДД.ММ.ГГГГ:\n"
            "Например: 25.12.2024"
        )
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_MANUAL_DATE)
        return
    
    if text == "🔙 Отмена":
        await safe_delete_ctx(f"create_trip_{user_id}")
        from handlers.menu import send_main_menu
        await send_main_menu(message)
        return
    
    selected_date = parse_calendar_date(text)
    if selected_date:
        await ctx.set(f"trip_date_{user_id}", selected_date)
        await message.answer(
            f"✅ Дата: {selected_date.strftime('%d.%m.%Y')}\n\n"
            "🕐 Введите время отправления в формате ЧЧ:ММ:\n"
            "Например: 14:30"
        )
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_TIME)
    else:
        await process_manual_date(message)

async def process_manual_date(message: Message):
    """Обрабатывает ручной ввод даты"""
    user_id = message.from_id
    
    try:
        date = datetime.strptime(message.text.strip(), "%d.%m.%Y")
        if date.date() < datetime.now().date():
            await message.answer("❌ Дата не может быть в прошлом")
            return
        
        await ctx.set(f"trip_date_{user_id}", date)
        await message.answer(
            f"✅ Дата: {date.strftime('%d.%m.%Y')}\n\n"
            "🕐 Введите время отправления в формате ЧЧ:ММ:\n"
            "Например: 14:30"
        )
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_TIME)
    except ValueError:
        await message.answer("❌ Неверный формат даты. Используйте ДД.ММ.ГГГГ")

async def process_time(message: Message):
    """Обрабатывает время после выбора даты"""
    user_id = message.from_id
    
    try:
        time = datetime.strptime(message.text.strip(), "%H:%M")
        date = await ctx.get(f"trip_date_{user_id}")
        
        if not date:
            await message.answer("❌ Ошибка. Начните создание поездки заново.")
            await safe_delete_ctx(f"create_trip_{user_id}")
            return
        
        dt = date.replace(hour=time.hour, minute=time.minute)
        
        if dt < datetime.now():
            await message.answer("❌ Дата и время не могут быть в прошлом")
            return
        
        await ctx.set(f"trip_datetime_{user_id}", dt)
        await safe_delete_ctx(f"trip_date_{user_id}")
        
        await message.answer("💺 Сколько свободных мест? (от 1 до 8)")
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_SEATS)
        
    except ValueError:
        await message.answer("❌ Неверный формат времени. Используйте ЧЧ:ММ")

async def process_seats(message: Message):
    """Обрабатывает количество мест и рассчитывает расстояние"""
    user_id = message.from_id
    
    try:
        seats = int(message.text.strip())
        if seats < 1 or seats > 8:
            await message.answer("❌ Количество мест должно быть от 1 до 8")
            return
        
        await ctx.set(f"trip_seats_{user_id}", seats)
        
        route_from = await ctx.get(f"trip_from_{user_id}")
        route_to = await ctx.get(f"trip_to_{user_id}")
        
        distance = None
        if settings.YANDEX_API_KEY and route_from and route_to:
            from utils.yandex_routing import geocode, haversine_distance
            coords_from = await geocode(route_from)
            coords_to = await geocode(route_to)
            if coords_from and coords_to:
                straight_distance = haversine_distance(coords_from, coords_to)
                logger.info(f"Straight distance: {route_from} -> {route_to} = {straight_distance:.1f} km")
                
                async for session in get_session():
                    coef_str = await get_setting(session, "road_coefficient", "1.4")
                coefficient = float(coef_str)
                distance = straight_distance * coefficient
                logger.info(f"Road distance (×{coefficient}): {distance:.1f} km")
        
        if distance:
            await ctx.set(f"trip_distance_{user_id}", distance)
        
        if distance:
            async for session in get_session():
                tariff_str = await get_setting(session, "price_per_km", "3.5")
            tariff = float(tariff_str)
            recommended_price = round_price(round(distance * tariff))
            await ctx.set(f"trip_recommended_price_{user_id}", recommended_price)
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text("✅ Подтвердить"), KeyboardButtonColor.POSITIVE)
            keyboard.add(Text("✏️ Своя цена"), KeyboardButtonColor.PRIMARY)
            
            await message.answer(
                f"📏 Расстояние: ~{distance:.0f} км\n"
                f"💰 Рекомендуемая цена: {recommended_price} ₽\n\n"
                "Нажмите «Подтвердить» или введите свою цену:",
                keyboard=keyboard.get_json()
            )
        else:
            await message.answer("💰 Введите цену за одно место (в рублях, 0 - бесплатно):")
        
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_PRICE)
        
    except ValueError:
        await message.answer("❌ Введите число от 1 до 8")

async def process_price(message: Message):
    """Обрабатывает цену (поддержка рекомендованной и своей)"""
    user_id = message.from_id
    text = message.text.strip()
    
    if text == "✏️ Своя цена":
        await message.answer("💰 Введите свою цену за место (в рублях):")
        return
    
    if text == "✅ Подтвердить":
        recommended_price = await ctx.get(f"trip_recommended_price_{user_id}")
        if recommended_price:
            price = recommended_price
            await ctx.set(f"trip_price_{user_id}", price)
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text("Пропустить комментарий"), KeyboardButtonColor.SECONDARY)
            
            await message.answer(
                f"✅ Принята рекомендованная цена: {price} ₽\n\n"
                "💬 Добавьте комментарий к поездке (или нажмите 'Пропустить комментарий'):",
                keyboard=keyboard.get_json()
            )
            await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_COMMENT)
            return
        else:
            await message.answer("💰 Введите цену за одно место (в рублях, 0 - бесплатно):")
            return
    
    try:
        price = int(text)
        if price < 0:
            await message.answer("❌ Цена не может быть отрицательной")
            return
        
        await ctx.set(f"trip_price_{user_id}", price)
        
        keyboard = Keyboard(inline=True)
        keyboard.add(Text("Пропустить комментарий"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            "💬 Добавьте комментарий к поездке (или нажмите 'Пропустить комментарий'):",
            keyboard=keyboard.get_json()
        )
        await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_COMMENT)
        
    except ValueError:
        await message.answer("❌ Введите целое число (0 - бесплатно)")

async def process_comment(message: Message):
    """Обрабатывает комментарий"""
    user_id = message.from_id
    
    if message.text == "Пропустить комментарий":
        comment = None
    else:
        comment = message.text.strip()
    
    await ctx.set(f"trip_comment_{user_id}", comment)
    
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("Да, на стену"), KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("Только в поиске"), KeyboardButtonColor.PRIMARY)
    
    await message.answer(
        "📢 Опубликовать поездку на стене группы?",
        keyboard=keyboard.get_json()
    )
    await ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_PUBLISH)

async def process_publish(message: Message):
    """Завершает создание поездки, публикует на стену и уведомляет подписчиков"""
    user_id = message.from_id
    
    publish_on_wall = message.text == "Да, на стену"
    
    route_from = await ctx.get(f"trip_from_{user_id}")
    route_to = await ctx.get(f"trip_to_{user_id}")
    departure_time = await ctx.get(f"trip_datetime_{user_id}")
    seats = await ctx.get(f"trip_seats_{user_id}")
    price = await ctx.get(f"trip_price_{user_id}")
    comment = await ctx.get(f"trip_comment_{user_id}")
    distance = await ctx.get(f"trip_distance_{user_id}")
    
    if not all([route_from, route_to, departure_time, seats is not None, price is not None]):
        await message.answer("❌ Произошла ошибка. Начните создание поездки заново.")
        await safe_delete_ctx(f"create_trip_{user_id}")
        return
    
    wall_published = False
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        
        if not user:
            await message.answer("❌ Пользователь не найден. Зарегистрируйтесь заново.")
            return
        
        trip = Trip(
            driver_id=user.id,
            route_from=route_from,
            route_to=route_to,
            departure_time=departure_time,
            seats_total=seats,
            seats_available=seats,
            price=price,
            comment=comment,
            distance=distance,
            status=TripStatus.active,
            publish_on_wall=publish_on_wall
        )
        
        session.add(trip)
        await session.commit()
        
        logger.info(f"Trip created: {trip.id} by user {user_id}" + 
                   (f" (distance: {distance:.0f} km)" if distance else ""))
        
        if publish_on_wall:
            try:
                api = API(token=settings.VK_GROUP_TOKEN)
                groups_response = await api.groups.get_by_id()
                group_id = -abs(groups_response.groups[0].id)
                
                wall_text = (
                    f"🚗 Новая поездка!\n\n"
                    f"📍 Маршрут: {route_from} → {route_to}\n"
                    f"📅 Дата и время: {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                    f"💺 Свободно мест: {seats}\n"
                    f"💰 Цена за место: {price}₽\n"
                )
                if comment:
                    wall_text += f"💬 Комментарий: {comment}\n"
                if distance:
                    wall_text += f"📏 Расстояние: {distance:.0f} км\n"
                wall_text += (
                    f"\n👤 Водитель: {user.first_name} {user.last_name}\n"
                    f"📩 Забронировать место: напишите в сообщения группы «Найти поездку»"
                )
                
                result = await api.wall.post(owner_id=group_id, message=wall_text, from_group=1)
                logger.info(f"Wall post published! Post ID: {result.post_id}")
                wall_published = True
            except Exception as e:
                logger.error(f"Failed to publish on wall: {type(e).__name__}: {e}")
        
        subs_result = await session.execute(
            select(Subscription).where(
                and_(
                    Subscription.route_from == route_from,
                    Subscription.route_to == route_to
                )
            )
        )
        subscriptions = subs_result.scalars().all()
        
        if subscriptions:
            notified_count = 0
            for sub in subscriptions:
                subscriber = await get_user_by_id(session, sub.user_id)
                if subscriber and subscriber.vk_id != user_id:
                    try:
                        api = API(token=settings.VK_GROUP_TOKEN)
                        keyboard = Keyboard(inline=True)
                        keyboard.add(Text(f"💬 Обсудить {trip.id}"), KeyboardButtonColor.PRIMARY)
                        keyboard.add(Text(f"✅ Бронировать {trip.id}"), KeyboardButtonColor.POSITIVE)
                        
                        await api.messages.send(
                            peer_ids=str(subscriber.vk_id),
                            message=(
                                f"🔔 Появилась поездка по вашему маршруту!\n\n"
                                f"🚗 {route_from} → {route_to}\n"
                                f"📅 {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                                f"💰 {price}₽\n"
                                f"💺 Мест: {seats}\n\n"
                                f"Выберите действие:"
                            ),
                            keyboard=keyboard.get_json(),
                            random_id=0
                        )
                        notified_count += 1
                        logger.info(f"Subscriber notified with buttons: {subscriber.vk_id}")
                    except Exception as e:
                        logger.error(f"Failed to notify subscriber {subscriber.vk_id}: {e}")
            
            if notified_count > 0:
                logger.info(f"Notified {notified_count} subscribers about trip {trip.id}")
        
        response = (
            f"✅ Поездка успешно создана!\n\n"
            f"📍 Маршрут: {route_from} → {route_to}\n"
            f"📅 Дата: {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"💺 Мест: {seats}\n"
            f"💰 Цена: {price}₽\n"
        )
        if distance:
            response += f"📏 Расстояние: {distance:.0f} км\n"
        if comment:
            response += f"💬 {comment}\n"
        if publish_on_wall and wall_published:
            response += "\n📢 Поездка опубликована на стене группы!"
        elif publish_on_wall and not wall_published:
            response += "\n⚠️ Не удалось опубликовать на стену (проверьте права токена)"
        
        await message.answer(response, keyboard=main_menu_keyboard())
    
    await safe_delete_ctx(f"create_trip_{user_id}")
    await safe_delete_ctx(f"trip_from_{user_id}")
    await safe_delete_ctx(f"trip_to_{user_id}")
    await safe_delete_ctx(f"trip_datetime_{user_id}")
    await safe_delete_ctx(f"trip_seats_{user_id}")
    await safe_delete_ctx(f"trip_price_{user_id}")
    await safe_delete_ctx(f"trip_comment_{user_id}")
    await safe_delete_ctx(f"trip_distance_{user_id}")
    await safe_delete_ctx(f"trip_recommended_price_{user_id}")
    await safe_delete_ctx(f"trip_date_{user_id}")
