from vkbottle import BaseStateGroup
from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import User, Rating, PendingRating, Trip, Booking, BookingStatus
from loguru import logger
from vkbottle import Keyboard, Text, KeyboardButtonColor, API
from utils.db_utils import get_user_by_vk_id, update_user_rating
from config import settings
from sqlalchemy import select, and_
from storage import ctx
from datetime import datetime, timezone

class RegistrationState(BaseStateGroup):
    WAITING_NAME = 1
    WAITING_AGE = 2
    WAITING_GENDER = 3
    WAITING_PHONE = 4

class EditProfileState(BaseStateGroup):
    CHOOSING_FIELD = 1
    EDITING_NAME = 2
    EDITING_AGE = 3
    EDITING_PHONE = 4

class RatingState(BaseStateGroup):
    WAITING_RATING = 100

# ============ Уведомления ============

async def send_notification(user_vk_id: int, message_text: str):
    """Отправляет уведомление пользователю через VK API"""
    try:
        api = API(token=settings.VK_GROUP_TOKEN)
        await api.messages.send(
            peer_ids=str(user_vk_id),
            message=message_text,
            random_id=0
        )
        logger.info(f"Notification sent to {user_vk_id}")
    except Exception as e:
        logger.error(f"Failed to send notification to {user_vk_id}: {e}")

# ============ Главное меню ============

async def send_main_menu(message: Message):
    await message.answer("🚗 Главное меню", keyboard=main_menu_keyboard())

async def start_handler(message: Message):
    user_id = message.from_id
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        
        if user is None:
            await message.answer(
                "Добро пожаловать! Давайте зарегистрируемся.\n"
                "Введите ваше имя и фамилию (например: Иван Иванов):"
            )
            await ctx.set(f"reg_state_{user_id}", RegistrationState.WAITING_NAME)
        else:
            if user.is_banned:
                await message.answer("❌ Ваш аккаунт заблокирован")
                return

            # Проверка временной блокировки
            if user.banned_until and user.banned_until > datetime.now(timezone.utc):
                await message.answer(
                    f"🚫 Вы временно заблокированы до {user.banned_until.strftime('%d.%m.%Y %H:%M')} (МСК) "
                    f"из-за отмены бронирования менее чем за 2 часа."
                )
                return
            
            if user.rating is not None:
                rating_text = f"Ваш рейтинг: {user.rating:.1f}⭐"
            else:
                rating_text = "У вас пока нет рейтинга"
            
            await message.answer(
                f"👤 С возвращением, {user.first_name}!\n{rating_text}",
                keyboard=main_menu_keyboard()
            )

async def process_name(message: Message):
    """Обрабатывает введенное имя и фамилию"""
    user_id = message.from_id
    full_name = message.text.strip()
    
    if full_name in ["Начать", "Меню", "👤 Профиль", "🔍 Найти поездку", "➕ Создать поездку", 
                      "🚗 ЛК Водителя", "🧑 ЛК Пассажира", "🛡️ Техподдержка",
                      "✏️ Редактировать профиль"]:
        await message.answer("❌ Пожалуйста, введите ваше имя и фамилию:")
        return
    
    parts = full_name.split()
    if len(parts) < 2:
        await message.answer(
            "❌ Пожалуйста, введите имя и фамилию через пробел.\n"
            "Например: Иван Иванов"
        )
        return
    
    first_name = parts[0]
    last_name = " ".join(parts[1:])
    
    await ctx.set(f"reg_first_name_{user_id}", first_name)
    await ctx.set(f"reg_last_name_{user_id}", last_name)
    
    await message.answer("📅 Введите ваш возраст (от 14 до 120):")
    await ctx.set(f"reg_state_{user_id}", RegistrationState.WAITING_AGE)

async def process_age(message: Message):
    """Обрабатывает возраст"""
    user_id = message.from_id
    
    try:
        age = int(message.text.strip())
        if age < 14 or age > 120:
            await message.answer("❌ Возраст должен быть от 14 до 120 лет. Попробуйте ещё раз:")
            return
        
        await ctx.set(f"reg_age_{user_id}", age)
        
        keyboard = Keyboard(inline=True)
        keyboard.add(Text("Мужской"), KeyboardButtonColor.PRIMARY)
        keyboard.add(Text("Женский"), KeyboardButtonColor.PRIMARY)
        
        await message.answer("👤 Выберите ваш пол:", keyboard=keyboard.get_json())
        await ctx.set(f"reg_state_{user_id}", RegistrationState.WAITING_GENDER)
        
    except ValueError:
        await message.answer("❌ Введите число (от 14 до 120):")

async def process_gender(message: Message):
    """Обрабатывает пол"""
    user_id = message.from_id
    gender = message.text.strip()
    
    if gender not in ["Мужской", "Женский"]:
        await message.answer("❌ Пожалуйста, выберите пол используя кнопки:")
        return
    
    await ctx.set(f"reg_gender_{user_id}", gender)
    
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("Пропустить"), KeyboardButtonColor.SECONDARY)
    
    await message.answer(
        "📱 Введите ваш номер телефона\n"
        "Например: +79991234567\n"
        "Или нажмите 'Пропустить':",
        keyboard=keyboard.get_json()
    )
    await ctx.set(f"reg_state_{user_id}", RegistrationState.WAITING_PHONE)

async def process_phone(message: Message):
    """Обрабатывает телефон и завершает регистрацию"""
    user_id = message.from_id
    phone = message.text.strip()
    
    if phone == "Пропустить":
        phone = None
    
    first_name = await ctx.get(f"reg_first_name_{user_id}")
    last_name = await ctx.get(f"reg_last_name_{user_id}")
    age = await ctx.get(f"reg_age_{user_id}")
    gender = await ctx.get(f"reg_gender_{user_id}")
    
    if not all([first_name, last_name, age, gender]):
        await message.answer("❌ Произошла ошибка. Начните регистрацию заново командой 'Начать'")
        await ctx.delete(f"reg_state_{user_id}")
        return
    
    async for session in get_session():
        existing_user = await get_user_by_vk_id(session, user_id)
        
        if existing_user:
            await message.answer(
                f"❌ Вы уже зарегистрированы как {existing_user.first_name} {existing_user.last_name}",
                keyboard=main_menu_keyboard()
            )
        else:
            user = User(
                vk_id=user_id,
                first_name=first_name,
                last_name=last_name,
                age=age,
                gender=gender,
                phone=phone,
                rating=None,
                rating_count=0,
                is_banned=False
            )
            session.add(user)
            await session.commit()
            
            logger.info(f"✅ Новый пользователь: {user_id} - {first_name} {last_name}")
            
            await message.answer(
                f"✅ Регистрация успешно завершена!\n\n"
                f"👤 Имя: {first_name} {last_name}\n"
                f"📅 Возраст: {age} лет\n"
                f"👤 Пол: {gender}\n"
                f"📱 Телефон: {phone or 'Не указан'}\n\n"
                f"Добро пожаловать в «Попутчик»! 🚗",
                keyboard=main_menu_keyboard()
            )
    
    await ctx.delete(f"reg_state_{user_id}")
    await ctx.delete(f"reg_first_name_{user_id}")
    await ctx.delete(f"reg_last_name_{user_id}")
    await ctx.delete(f"reg_age_{user_id}")
    await ctx.delete(f"reg_gender_{user_id}")

# ============ Редактирование профиля ============

async def edit_profile_handler(message: Message):
    """Начинает редактирование профиля"""
    user_id = message.from_id
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь!")
            return
        
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("👤 Изменить имя"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("📅 Изменить возраст"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("📱 Изменить телефон"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(
            f"✏️ Редактирование профиля\n\n"
            f"Текущие данные:\n"
            f"Имя: {user.first_name} {user.last_name}\n"
            f"Возраст: {user.age}\n"
            f"Телефон: {user.phone or 'Не указан'}\n\n"
            f"Что хотите изменить?",
            keyboard=keyboard.get_json()
        )
        await ctx.set(f"edit_state_{user_id}", EditProfileState.CHOOSING_FIELD)

async def process_edit_choice(message: Message):
    """Обрабатывает выбор поля для редактирования"""
    user_id = message.from_id
    choice = message.text.strip()
    
    if choice == "👤 Изменить имя":
        await message.answer("Введите новое имя и фамилию (например: Иван Иванов):")
        await ctx.set(f"edit_state_{user_id}", EditProfileState.EDITING_NAME)
    elif choice == "📅 Изменить возраст":
        await message.answer("Введите новый возраст (от 14 до 120):")
        await ctx.set(f"edit_state_{user_id}", EditProfileState.EDITING_AGE)
    elif choice == "📱 Изменить телефон":
        keyboard = Keyboard(inline=True)
        keyboard.add(Text("Удалить телефон"), KeyboardButtonColor.NEGATIVE)
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        await message.answer(
            "Введите новый номер телефона или нажмите 'Удалить телефон':",
            keyboard=keyboard.get_json()
        )
        await ctx.set(f"edit_state_{user_id}", EditProfileState.EDITING_PHONE)
    elif choice == "🔙 В меню":
        await ctx.delete(f"edit_state_{user_id}")
        await send_main_menu(message)
    else:
        await message.answer("❌ Пожалуйста, выберите действие из меню")

async def process_edit_name(message: Message):
    """Обрабатывает изменение имени"""
    user_id = message.from_id
    full_name = message.text.strip()
    parts = full_name.split()
    
    if len(parts) < 2:
        await message.answer("❌ Введите имя и фамилию через пробел")
        return
    
    first_name = parts[0]
    last_name = " ".join(parts[1:])
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        user.first_name = first_name
        user.last_name = last_name
        await session.commit()
        
        logger.info(f"✅ Пользователь {user_id} изменил имя на {first_name} {last_name}")
        
        await message.answer(
            f"✅ Имя изменено на: {first_name} {last_name}",
            keyboard=main_menu_keyboard()
        )
    
    await ctx.delete(f"edit_state_{user_id}")

async def process_edit_age(message: Message):
    """Обрабатывает изменение возраста"""
    user_id = message.from_id
    
    try:
        age = int(message.text.strip())
        if age < 14 or age > 120:
            await message.answer("❌ Возраст должен быть от 14 до 120 лет")
            return
        
        async for session in get_session():
            user = await get_user_by_vk_id(session, user_id)
            user.age = age
            await session.commit()
            
            logger.info(f"✅ Пользователь {user_id} изменил возраст на {age}")
            
            await message.answer(
                f"✅ Возраст изменен на: {age} лет",
                keyboard=main_menu_keyboard()
            )
        
        await ctx.delete(f"edit_state_{user_id}")
    except ValueError:
        await message.answer("❌ Введите число от 14 до 120")

async def process_edit_phone(message: Message):
    """Обрабатывает изменение телефона"""
    user_id = message.from_id
    phone = message.text.strip()
    
    if phone == "Удалить телефон":
        phone = None
    elif phone == "🔙 В меню":
        await ctx.delete(f"edit_state_{user_id}")
        await send_main_menu(message)
        return
    
    async for session in get_session():
        user = await get_user_by_vk_id(session, user_id)
        user.phone = phone
        await session.commit()
        
        logger.info(f"✅ Пользователь {user_id} изменил телефон на {phone or 'Не указан'}")
        
        await message.answer(
            f"✅ Телефон изменен на: {phone or 'Не указан'}",
            keyboard=main_menu_keyboard()
        )
    
    await ctx.delete(f"edit_state_{user_id}")

# ============ Система рейтинга ============

async def send_rating_request(user_id: int, trip_id: int, target_id: int, target_name: str):
    """Отправляет запрос на оценку пользователю"""
    api = API(token=settings.VK_GROUP_TOKEN)
    
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("1⭐"), KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("2⭐"), KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("3⭐"), KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("4⭐"), KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("5⭐"), KeyboardButtonColor.SECONDARY)
    
    try:
        await api.messages.send(
            peer_ids=str(user_id),
            message=f"⭐ Оцените поездку с {target_name} (от 1 до 5):",
            keyboard=keyboard.get_json(),
            random_id=0
        )
        logger.info(f"Rating request sent to {user_id}")
    except Exception as e:
        logger.error(f"Failed to send rating request to {user_id}: {e}")

async def send_next_rating_request(session, user_vk_id: int):
    """Отправляет только самый ранний ожидающий запрос оценки этого пользователя."""
    result = await session.execute(
        select(PendingRating)
        .where(PendingRating.from_user_vk_id == user_vk_id)
        .order_by(PendingRating.id.asc())
        .limit(1)
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return

    try:
        api = API(token=settings.VK_GROUP_TOKEN)
        keyboard = Keyboard(inline=True)
        for value in range(1, 6):
            keyboard.add(Text(f"{value}⭐"), KeyboardButtonColor.SECONDARY)

        await api.messages.send(
            peer_ids=str(user_vk_id),
            message=(
                f"⭐ Оцените поездку с {pending.target_name or 'участником поездки'} "
                "(от 1 до 5). Если у вас несколько оценок, запросы придут по очереди."
            ),
            keyboard=keyboard.get_json(),
            random_id=0
        )
    except Exception as e:
        logger.error(f"Failed to send next rating request to {user_vk_id}: {e}")


async def process_rating(message: Message):
    """Сохраняет оценку для конкретной брони, а не путает ID поездки и брони."""
    user_vk_id = message.from_id
    text = message.text.strip()

    try:
        rating_value = int(text[0])
        if rating_value < 1 or rating_value > 5:
            await message.answer("❌ Оценка должна быть от 1 до 5")
            return
    except (ValueError, IndexError):
        await message.answer("❌ Пожалуйста, выберите оценку от 1 до 5")
        return

    async for session in get_session():
        pending_result = await session.execute(
            select(PendingRating)
            .where(PendingRating.from_user_vk_id == user_vk_id)
            .order_by(PendingRating.id.asc())
            .limit(1)
            .with_for_update()
        )
        pending = pending_result.scalar_one_or_none()

        if not pending:
            await message.answer("❌ У вас нет ожидающих оценок")
            return

        from_user = await get_user_by_vk_id(session, user_vk_id)
        if not from_user:
            await session.delete(pending)
            await session.commit()
            await message.answer("❌ Пользователь не найден")
            return

        trip = await session.get(Trip, pending.trip_id)
        booking = None

        if trip:
            if trip.driver_id == from_user.id:
                booking_result = await session.execute(
                    select(Booking).where(
                        and_(
                            Booking.trip_id == trip.id,
                            Booking.passenger_id == pending.to_user_id,
                            Booking.status == BookingStatus.accepted
                        )
                    ).order_by(Booking.id.asc()).limit(1)
                )
            elif pending.to_user_id == trip.driver_id:
                booking_result = await session.execute(
                    select(Booking).where(
                        and_(
                            Booking.trip_id == trip.id,
                            Booking.passenger_id == from_user.id,
                            Booking.status == BookingStatus.accepted
                        )
                    ).order_by(Booking.id.asc()).limit(1)
                )
            else:
                booking_result = None

            if booking_result is not None:
                booking = booking_result.scalar_one_or_none()

        # Совместимость с уже созданными старыми PendingRating, где в trip_id
        # ошибочно записывался booking.id вместо trip.id.
        if booking is None:
            legacy_booking = await session.get(Booking, pending.trip_id)
            if legacy_booking:
                legacy_trip = await session.get(Trip, legacy_booking.trip_id)
                if legacy_trip and (
                    (legacy_trip.driver_id == from_user.id and
                     legacy_booking.passenger_id == pending.to_user_id) or
                    (legacy_trip.driver_id == pending.to_user_id and
                     legacy_booking.passenger_id == from_user.id)
                ):
                    booking = legacy_booking

        if booking is None:
            await session.delete(pending)
            await session.commit()
            await message.answer(
                "❌ Не удалось связать старый запрос оценки с бронированием. "
                "Этот запрос удалён, остальные оценки сохранены."
            )
            await send_next_rating_request(session, user_vk_id)
            return

        existing = await session.execute(
            select(Rating.id).where(
                and_(
                    Rating.booking_id == booking.id,
                    Rating.from_user_id == from_user.id
                )
            ).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            await session.delete(pending)
            await session.commit()
            await message.answer("❌ Вы уже оценили эту поездку")
            await send_next_rating_request(session, user_vk_id)
            return

        rating = Rating(
            booking_id=booking.id,
            from_user_id=from_user.id,
            to_user_id=pending.to_user_id,
            value=rating_value
        )
        target_id = pending.to_user_id
        session.add(rating)
        await session.delete(pending)
        await update_user_rating(session, target_id)
        await session.commit()

        await message.answer(
            f"✅ Спасибо за оценку! Вы поставили {rating_value}⭐",
            keyboard=main_menu_keyboard()
        )
        logger.info(
            f"Rating {rating_value} from {from_user.id} to {target_id} for booking {booking.id}"
        )
        await send_next_rating_request(session, user_vk_id)
