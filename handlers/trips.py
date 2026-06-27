from vkbottle import BaseStateGroup, CtxStorage, API
from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import User, Trip, TripStatus, Subscription
from datetime import datetime
from loguru import logger
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_user_by_vk_id, get_user_by_id, get_setting
from config import settings
from sqlalchemy import select, and_

ctx = CtxStorage()

class CreateTripState(BaseStateGroup):
    WAITING_ROUTE = 1
    WAITING_DATETIME = 2
    WAITING_SEATS = 3
    WAITING_PRICE = 4
    WAITING_COMMENT = 5
    WAITING_PUBLISH = 6

def safe_delete_ctx(key: str):
    """Безопасное удаление ключа из контекста"""
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

def round_price(price: int) -> int:
    """Округляет цену до десятков: 324 → 320, 326 → 330"""
    return round(price / 10) * 10

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
    
    await message.answer(
        "➕ Создание поездки\n\n"
        "Введите маршрут в формате:\n"
        "• Город1-Город2 (например: Уфа-Туймазы)\n"
        "• Город1 Город2 (например: Уфа Туймазы)"
    )
    ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_ROUTE)

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
    
    ctx.set(f"trip_from_{user_id}", route_from)
    ctx.set(f"trip_to_{user_id}", route_to)
    
    await message.answer(
        f"📍 Маршрут: {route_from} → {route_to}\n\n"
        "📅 Введите дату и время отправления в формате: ДД.ММ.ГГГГ ЧЧ:ММ\n"
        "Например: 25.12.2024 14:30"
    )
    ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_DATETIME)

async def process_datetime(message: Message):
    """Обрабатывает дату и время"""
    user_id = message.from_id
    
    try:
        dt = datetime.strptime(message.text.strip(), "%d.%m.%Y %H:%M")
        
        if dt < datetime.now():
            await message.answer("❌ Дата и время не могут быть в прошлом")
            return
        
        ctx.set(f"trip_datetime_{user_id}", dt)
        
        await message.answer("💺 Сколько свободных мест? (от 1 до 8)")
        ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_SEATS)
        
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Используйте: ДД.ММ.ГГГГ ЧЧ:ММ\n"
            "Например: 25.12.2024 14:30"
        )

async def process_seats(message: Message):
    """Обрабатывает количество мест и рассчитывает расстояние"""
    user_id = message.from_id
    
    try:
        seats = int(message.text.strip())
        if seats < 1 or seats > 8:
            await message.answer("❌ Количество мест должно быть от 1 до 8")
            return
        
        ctx.set(f"trip_seats_{user_id}", seats)
        
        # Пытаемся рассчитать расстояние
        route_from = ctx.get(f"trip_from_{user_id}")
        route_to = ctx.get(f"trip_to_{user_id}")
        
        distance = None
        if settings.YANDEX_API_KEY and route_from and route_to:
            from utils.yandex_routing import geocode, haversine_distance
            coords_from = await geocode(route_from)
            coords_to = await geocode(route_to)
            if coords_from and coords_to:
                straight_distance = haversine_distance(coords_from, coords_to)
                logger.info(f"Straight distance: {route_from} -> {route_to} = {straight_distance:.1f} km")
                
                # Применяем дорожный коэффициент
                async for session in get_session():
                    coef_str = await get_setting(session, "road_coefficient", "1.4")
                coefficient = float(coef_str)
                distance = straight_distance * coefficient
                logger.info(f"Road distance (×{coefficient}): {distance:.1f} km")
        
        # Сохраняем дорожное расстояние
        if distance:
            ctx.set(f"trip_distance_{user_id}", distance)
        
        if distance:
            # Показываем рекомендованную цену с дорожным расстоянием
            async for session in get_session():
                tariff_str = await get_setting(session, "price_per_km", "3.5")
            tariff = float(tariff_str)
            recommended_price = round_price(round(distance * tariff))
            ctx.set(f"trip_recommended_price_{user_id}", recommended_price)
            
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
            # Без расстояния - обычный запрос цены
            await message.answer("💰 Введите цену за одно место (в рублях, 0 - бесплатно):")
        
        ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_PRICE)
        
    except ValueError:
        await message.answer("❌ Введите число от 1 до 8")

async def process_price(message: Message):
    """Обрабатывает цену (поддержка рекомендованной и своей)"""
    user_id = message.from_id
    text = message.text.strip()
    
    # Если нажал "Своя цена"
    if text == "✏️ Своя цена":
        await message.answer("💰 Введите свою цену за место (в рублях):")
        return
    
    # Если нажал "Подтвердить" и есть рекомендованная цена
    if text == "✅ Подтвердить":
        recommended_price = ctx.get(f"trip_recommended_price_{user_id}")
        if recommended_price:
            price = recommended_price
            ctx.set(f"trip_price_{user_id}", price)
            
            keyboard = Keyboard(inline=True)
            keyboard.add(Text("Пропустить комментарий"), KeyboardButtonColor.SECONDARY)
            
            await message.answer(
                f"✅ Принята рекомендованная цена: {price} ₽\n\n"
                "💬 Добавьте комментарий к поездке (или нажмите 'Пропустить комментарий'):",
                keyboard=keyboard.get_json()
            )
            ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_COMMENT)
            return
        else:
            await message.answer("💰 Введите цену за одно место (в рублях, 0 - бесплатно):")
            return
    
    # Обычный ввод цены числом
    try:
        price = int(text)
        if price < 0:
            await message.answer("❌ Цена не может быть отрицательной")
            return
        
        ctx.set(f"trip_price_{user_id}", price)
        
        keyboard = Keyboard(inline=True)
        keyboard.add(Text("Пропустить комментарий"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            "💬 Добавьте комментарий к поездке (или нажмите 'Пропустить комментарий'):",
            keyboard=keyboard.get_json()
        )
        ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_COMMENT)
        
    except ValueError:
        await message.answer("❌ Введите целое число (0 - бесплатно)")

async def process_comment(message: Message):
    """Обрабатывает комментарий"""
    user_id = message.from_id
    
    if message.text == "Пропустить комментарий":
        comment = None
    else:
        comment = message.text.strip()
    
    ctx.set(f"trip_comment_{user_id}", comment)
    
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("Да, на стену"), KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("Только в поиске"), KeyboardButtonColor.PRIMARY)
    
    await message.answer(
        "📢 Опубликовать поездку на стене группы?",
        keyboard=keyboard.get_json()
    )
    ctx.set(f"create_trip_{user_id}", CreateTripState.WAITING_PUBLISH)

async def process_publish(message: Message):
    """Завершает создание поездки, публикует на стену и уведомляет подписчиков"""
    user_id = message.from_id
    
    publish_on_wall = message.text == "Да, на стену"
    
    route_from = ctx.get(f"trip_from_{user_id}")
    route_to = ctx.get(f"trip_to_{user_id}")
    departure_time = ctx.get(f"trip_datetime_{user_id}")
    seats = ctx.get(f"trip_seats_{user_id}")
    price = ctx.get(f"trip_price_{user_id}")
    comment = ctx.get(f"trip_comment_{user_id}")
    distance = ctx.get(f"trip_distance_{user_id}")
    
    if not all([route_from, route_to, departure_time, seats is not None, price is not None]):
        await message.answer("❌ Произошла ошибка. Начните создание поездки заново.")
        safe_delete_ctx(f"create_trip_{user_id}")
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
        
        # Публикация на стену
        if publish_on_wall:
            try:
                api = API(token=settings.VK_GROUP_TOKEN)
                
                groups_response = await api.groups.get_by_id()
                group_id = -abs(groups_response.groups[0].id)
                logger.info(f"Publishing to wall, group_id: {group_id}")
                
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
                
                result = await api.wall.post(
                    owner_id=group_id,
                    message=wall_text,
                    from_group=1
                )
                logger.info(f"Wall post published! Post ID: {result.post_id}")
                wall_published = True
                
            except Exception as e:
                logger.error(f"Failed to publish on wall: {type(e).__name__}: {e}")
        
        # Уведомление подписчикам
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
                    from handlers.menu import send_notification
                    await send_notification(
                        subscriber.vk_id,
                        f"🔔 Появилась поездка по вашему маршруту!\n\n"
                        f"🚗 {route_from} → {route_to}\n"
                        f"📅 {departure_time.strftime('%d.%m.%Y %H:%M')}\n"
                        f"💰 {price}₽\n"
                        f"💺 Мест: {seats}\n\n"
                        f"Зайдите в бот и нажмите «🔍 Найти поездку» чтобы забронировать!"
                    )
                    notified_count += 1
            
            if notified_count > 0:
                logger.info(f"Notified {notified_count} subscribers about trip {trip.id}")
        
        # Ответ пользователю
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
    
    # Очищаем все данные
    safe_delete_ctx(f"create_trip_{user_id}")
    safe_delete_ctx(f"trip_from_{user_id}")
    safe_delete_ctx(f"trip_to_{user_id}")
    safe_delete_ctx(f"trip_datetime_{user_id}")
    safe_delete_ctx(f"trip_seats_{user_id}")
    safe_delete_ctx(f"trip_price_{user_id}")
    safe_delete_ctx(f"trip_comment_{user_id}")
    safe_delete_ctx(f"trip_distance_{user_id}")
    safe_delete_ctx(f"trip_recommended_price_{user_id}")