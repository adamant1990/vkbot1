from vkbottle.bot import Message
from config import settings
from db import get_session
from models import User, Trip, Booking, Rating
from sqlalchemy import select, func
from loguru import logger
import os
import asyncio
from vkbottle import Keyboard, Text, KeyboardButtonColor
from utils.db_utils import get_setting, set_setting, get_user_by_vk_id
from storage import ctx
from keyboards import main_menu_keyboard

async def admin_handler(message: Message):
    if message.from_id not in settings.admin_ids_list:
        await message.answer("❌ Недостаточно прав")
        return
    
    keyboard = Keyboard(inline=False)
    keyboard.add(Text("📊 Статистика"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("👥 Пользователи"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("🚗 Поездки"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("📩 Заявки"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("👥 Рейтинги"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("⚙️ Настройки"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📢 Рассылка"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("📋 Логи"), KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
    
    await message.answer("🔐 Админ-панель:", keyboard=keyboard.get_json())

async def stats_handler(message: Message):
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        users_count = await session.scalar(select(func.count(User.id)))
        trips_count = await session.scalar(select(func.count(Trip.id)))
        active_trips = await session.scalar(
            select(func.count(Trip.id)).where(Trip.status == "active")
        )
        bookings_count = await session.scalar(select(func.count(Booking.id)))
        ratings_count = await session.scalar(select(func.count(Rating.id)))
        
        stats_text = (
            f"📊 Статистика бота:\n\n"
            f"👥 Пользователей: {users_count}\n"
            f"🚗 Всего поездок: {trips_count}\n"
            f"✅ Активных поездок: {active_trips}\n"
            f"📩 Бронирований: {bookings_count}\n"
            f"⭐ Оценок: {ratings_count}\n"
        )
        
        keyboard = Keyboard(inline=True)
        keyboard.add(Text("🔙 В админ-панель"), KeyboardButtonColor.SECONDARY)
        await message.answer(stats_text, keyboard=keyboard.get_json())

async def users_list_handler(message: Message):
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        result = await session.execute(
            select(User).order_by(User.id).limit(20)
        )
        users = result.scalars().all()
        
        users_text = "👥 Последние пользователи:\n\n"
        for user in users:
            status = "🚫 Забанен" if user.is_banned else "✅ Активен"
            rating = f"{user.rating:.1f}⭐" if user.rating else "Нет"
            users_text += (
                f"ID: {user.vk_id} | {user.first_name} {user.last_name}\n"
                f"Рейтинг: {rating} | Статус: {status}\n\n"
            )
        
        await message.answer(users_text)

async def trips_admin_handler(message: Message):
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        result = await session.execute(
            select(Trip).order_by(Trip.created_at.desc()).limit(10)
        )
        trips = result.scalars().all()
        
        trips_text = "🚗 Последние поездки:\n\n"
        for trip in trips:
            distance_info = f" | Расстояние: {trip.distance:.1f} км" if trip.distance else ""
            trips_text += (
                f"#{trip.id} | {trip.route_from} → {trip.route_to}\n"
                f"Дата: {trip.departure_time} | Мест: {trip.seats_available}{distance_info}\n"
                f"Цена: {trip.price}₽ | Статус: {trip.status.value}\n\n"
            )
        
        await message.answer(trips_text)

async def logs_handler(message: Message):
    if message.from_id not in settings.admin_ids_list:
        return
    
    log_file = settings.LOG_FILE
    if not os.path.exists(log_file):
        await message.answer("📋 Лог-файл не найден")
        return
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-20:] if len(lines) > 20 else lines
        
        logs_text = "📋 Последние строки логов:\n\n" + "".join(last_lines)
        
        if len(logs_text) > 4000:
            logs_text = logs_text[-4000:]
        
        await message.answer(logs_text[:4000])
    except Exception as e:
        logger.error(f"Error reading logs: {e}")
        await message.answer(f"❌ Ошибка чтения логов: {e}")

# ============ Рассылка ============

async def broadcast_handler(message: Message):
    """Запрашивает текст для рассылки"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    await message.answer(
        "📢 Введите текст сообщения для рассылки всем пользователям.\n"
        "Для отмены нажмите '🔙 В админ-панель'"
    )
    await ctx.set(f"admin_broadcast_{message.from_id}", True)

async def process_broadcast(message: Message):
    """Отправляет рассылку всем пользователям"""
    user_id = message.from_id
    
    if message.text == "🔙 В админ-панель":
        try:
            await ctx.delete(f"admin_broadcast_{user_id}")
        except Exception:
            pass
        await admin_handler(message)
        return
    
    async for session in get_session():
        result = await session.execute(select(User.vk_id))
        users = result.scalars().all()
        
        sent_count = 0
        for vk_id in users:
            try:
                from handlers.menu import send_notification
                await send_notification(vk_id, f"📢 Рассылка:\n\n{message.text}")
                sent_count += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Failed to send broadcast to {vk_id}: {e}")
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("🔙 В админ-панель"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"✅ Рассылка отправлена {sent_count} из {len(users)} пользователям!",
            keyboard=keyboard.get_json()
        )
    
    try:
        await ctx.delete(f"admin_broadcast_{user_id}")
    except Exception:
        pass

# ============ Управление пользователями (Рейтинги) ============

async def safe_ctx_delete(key: str):
    """Безопасное удаление ключа из контекста"""
    try:
        await ctx.delete(key)
    except Exception:
        pass

async def users_management_handler(message: Message):
    """Показывает список пользователей с кнопками управления"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    await ctx.set(f"admin_users_page_{message.from_id}", 0)
    await safe_ctx_delete(f"admin_users_search_{message.from_id}")
    
    await show_users_page(message, message.from_id, 0)

async def show_users_page(message: Message, user_id: int, page: int):
    """Показывает страницу пользователей"""
    search = await ctx.get(f"admin_users_search_{user_id}")
    
    async for session in get_session():
        if search:
            if search.isdigit():
                query = select(User).where(
                    (User.vk_id == int(search)) | 
                    (User.first_name.ilike(f"%{search}%")) |
                    (User.last_name.ilike(f"%{search}%"))
                )
            else:
                query = select(User).where(
                    (User.first_name.ilike(f"%{search}%")) |
                    (User.last_name.ilike(f"%{search}%"))
                )
        else:
            query = select(User)
        
        count_query = select(func.count()).select_from(query.subquery())
        total = await session.scalar(count_query)
        
        per_page = 5
        offset = page * per_page
        total_pages = max(1, (total - 1) // per_page + 1)
        
        users = (await session.execute(
            query.order_by(User.id.desc()).offset(offset).limit(per_page)
        )).scalars().all()
        
        if not users:
            await message.answer("👥 Пользователи не найдены")
            return
        
        users_text = f"👥 Пользователи ({offset + 1}-{min(offset + per_page, total)} из {total}):\n\n"
        
        for i, user in enumerate(users, 1):
            status = "🚫" if user.is_banned else "✅"
            rating = f"{user.rating:.1f}⭐" if user.rating else "—"
            users_text += (
                f"{i}. {user.first_name} {user.last_name} | {rating} | {status}\n"
                f"   ID: {user.vk_id} | 📱{user.phone or '—'}\n\n"
            )
        
        keyboard = Keyboard(inline=False)
        for i, user in enumerate(users, 1):
            ban_text = "✅ Разбанить" if user.is_banned else "🚫 Забанить"
            keyboard.add(Text(f"{ban_text} {user.vk_id}"), 
                        KeyboardButtonColor.NEGATIVE if not user.is_banned else KeyboardButtonColor.POSITIVE)
            keyboard.add(Text(f"⭐ Рейтинг {user.vk_id}"), KeyboardButtonColor.PRIMARY)
            keyboard.add(Text(f"🔄 Сбросить {user.vk_id}"), KeyboardButtonColor.SECONDARY)
            keyboard.row()
        
        if total_pages > 1:
            if page > 0:
                keyboard.add(Text("⬅ Назад"), KeyboardButtonColor.PRIMARY)
            if page < total_pages - 1:
                keyboard.add(Text("Вперёд ➡"), KeyboardButtonColor.PRIMARY)
            keyboard.row()
        
        keyboard.add(Text("🔍 Поиск"), KeyboardButtonColor.PRIMARY)
        keyboard.add(Text("🔙 В админ-панель"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(users_text, keyboard=keyboard.get_json())
        await ctx.set(f"admin_users_page_{user_id}", page)


async def users_navigation_handler(message: Message):
    """Обрабатывает навигацию по пользователям"""
    user_id = message.from_id
    current_page = await ctx.get(f"admin_users_page_{user_id}")
    if current_page is None:
        current_page = 0
    
    if "Назад" in message.text:
        new_page = max(0, current_page - 1)
    elif "Вперёд" in message.text:
        new_page = current_page + 1
    else:
        return
    
    await show_users_page(message, user_id, new_page)


async def search_users_handler(message: Message):
    """Запрашивает поисковый запрос"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    await message.answer(
        "🔍 Введите ID пользователя или имя для поиска:\n"
        "Для отмены нажмите '🔙 В админ-панель'"
    )
    await ctx.set(f"admin_users_search_input_{message.from_id}", True)


async def process_users_search(message: Message):
    """Выполняет поиск пользователей"""
    user_id = message.from_id
    
    if message.text == "🔙 В админ-панель":
        await safe_ctx_delete(f"admin_users_search_input_{user_id}")
        await admin_handler(message)
        return
    
    await ctx.set(f"admin_users_search_{user_id}", message.text.strip())
    await ctx.set(f"admin_users_page_{user_id}", 0)
    await safe_ctx_delete(f"admin_users_search_input_{user_id}")
    
    await show_users_page(message, user_id, 0)


async def ban_user_handler(message: Message):
    """Банит/разбанивает пользователя"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    vk_id = int(message.text.split()[-1])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, vk_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        if "Забанить" in message.text:
            user.is_banned = True
            await session.commit()
            await message.answer(f"🚫 Пользователь {user.first_name} {user.last_name} забанен")
            from handlers.menu import send_notification
            await send_notification(vk_id, "🚫 Ваш аккаунт заблокирован администратором.")
        else:
            user.is_banned = False
            await session.commit()
            await message.answer(f"✅ Пользователь {user.first_name} {user.last_name} разбанен")
            from handlers.menu import send_notification
            await send_notification(vk_id, "✅ Ваш аккаунт разблокирован.")
        
        logger.info(f"User {vk_id} {'banned' if user.is_banned else 'unbanned'} by admin {message.from_id}")


async def change_rating_handler(message: Message):
    """Запрашивает новый рейтинг для пользователя"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    vk_id = int(message.text.split()[-1])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, vk_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        await message.answer(
            f"Введите новый рейтинг для {user.first_name} {user.last_name} (0-5):\n"
            f"Текущий: {user.rating or 'нет'}\n"
            "Для отмены нажмите '🔙 В админ-панель'"
        )
        await ctx.set(f"admin_change_rating_{message.from_id}", vk_id)


async def process_change_rating(message: Message):
    """Сохраняет новый рейтинг пользователя"""
    user_id = message.from_id
    target_vk_id = await ctx.get(f"admin_change_rating_{user_id}")
    
    if message.text == "🔙 В админ-панель":
        await safe_ctx_delete(f"admin_change_rating_{user_id}")
        await admin_handler(message)
        return
    
    try:
        new_rating = float(message.text.strip().replace(',', '.'))
        if new_rating < 0 or new_rating > 5:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 0 до 5")
        return
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, target_vk_id)
        if user:
            user.rating = new_rating
            user.rating_count = max(user.rating_count, 1)
            await session.commit()
            
            await message.answer(
                f"✅ Рейтинг пользователя {user.first_name} {user.last_name} изменён на {new_rating}⭐"
            )
            logger.info(f"Admin {user_id} changed rating of {target_vk_id} to {new_rating}")
    
    await safe_ctx_delete(f"admin_change_rating_{user_id}")


async def reset_rating_handler(message: Message):
    """Сбрасывает рейтинг пользователя"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    vk_id = int(message.text.split()[-1])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, vk_id)
        if not user:
            await message.answer("❌ Пользователь не найден")
            return
        
        user.rating = None
        user.rating_count = 0
        
        ratings = (await session.execute(
            select(Rating).where(Rating.to_user_id == user.id)
        )).scalars().all()
        for r in ratings:
            await session.delete(r)
        
        await session.commit()
        
        await message.answer(f"🔄 Рейтинг пользователя {user.first_name} {user.last_name} сброшен")
        logger.info(f"Admin {message.from_id} reset rating of {vk_id}")

# ============ Управление настройками ============

async def price_settings_handler(message: Message):
    """Показывает текущие настройки"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        tariff = await get_setting(session, "price_per_km", "3.5")
        coefficient = await get_setting(session, "road_coefficient", "1.4")
        max_angle = await get_setting(session, "max_angle", "110")
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("✏️ Изменить тариф"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("📐 Изменить коэффициент"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🧭 Изменить макс. угол"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🔙 В админ-панель"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"⚙️ Настройки\n\n"
            f"Тариф за км: {tariff} ₽/км\n"
            f"Дорожный коэффициент: {coefficient}\n"
            f"Макс. угол отклонения: {max_angle}°\n"
            f"(если угол между направлениями больше — не считается попутным)\n\n"
            "Выберите что изменить:",
            keyboard=keyboard.get_json()
        )

async def change_tariff_handler(message: Message):
    """Запрашивает новый тариф"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    await message.answer(
        "Введите новый тариф за км (например: 4.5):\n"
        "Для отмены нажмите '🔙 В админ-панель'"
    )
    await ctx.set(f"admin_change_tariff_{message.from_id}", True)

async def change_coefficient_handler(message: Message):
    """Запрашивает новый дорожный коэффициент"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        coefficient = await get_setting(session, "road_coefficient", "1.4")
    
    await message.answer(
        f"Текущий коэффициент: {coefficient}\n"
        "Введите новый дорожный коэффициент (например: 1.5):\n"
        "Для отмены нажмите '🔙 В админ-панель'"
    )
    await ctx.set(f"admin_change_coefficient_{message.from_id}", True)

async def change_angle_handler(message: Message):
    """Запрашивает новый максимальный угол"""
    if message.from_id not in settings.admin_ids_list:
        return
    
    async for session in get_session():
        max_angle = await get_setting(session, "max_angle", "110")
    
    await message.answer(
        f"Текущий макс. угол: {max_angle}°\n"
        "Введите новый угол (20-180, рекомендуется 100-110):\n"
        "Для отмены нажмите '🔙 В админ-панель'"
    )
    await ctx.set(f"admin_change_angle_{message.from_id}", True)

async def process_new_tariff(message: Message):
    """Сохраняет новый тариф"""
    user_id = message.from_id
    
    if message.text == "🔙 В админ-панель":
        await safe_ctx_delete(f"admin_change_tariff_{user_id}")
        await price_settings_handler(message)
        return
    
    try:
        new_tariff = float(message.text.strip().replace(',', '.'))
        if new_tariff <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите положительное число (например: 4.5)")
        return
    
    async for session in get_session():
        await set_setting(session, "price_per_km", str(new_tariff))
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("🔙 К настройкам"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"✅ Тариф изменён на {new_tariff} ₽/км",
            keyboard=keyboard.get_json()
        )
    
    await safe_ctx_delete(f"admin_change_tariff_{user_id}")

async def process_new_coefficient(message: Message):
    """Сохраняет новый дорожный коэффициент"""
    user_id = message.from_id
    
    if message.text == "🔙 В админ-панель":
        await safe_ctx_delete(f"admin_change_coefficient_{user_id}")
        await price_settings_handler(message)
        return
    
    try:
        new_coef = float(message.text.strip().replace(',', '.'))
        if new_coef < 1.0 or new_coef > 3.0:
            await message.answer("❌ Коэффициент должен быть от 1.0 до 3.0")
            return
    except ValueError:
        await message.answer("❌ Введите число (например: 1.5)")
        return
    
    async for session in get_session():
        await set_setting(session, "road_coefficient", str(new_coef))
        
        k
