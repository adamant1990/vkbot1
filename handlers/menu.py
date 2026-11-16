from vkbottle import BaseStateGroup
from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from models import User, Rating, PendingRating, Booking, Trip
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

async def process_rating(message: Message):
    """Сохраняет оценку только для конкретного запроса из payload кнопки."""
    import json

    user_vk_id = message.from_id
    payload = getattr(message, "payload", None)

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            payload = None

    if not isinstance(payload, dict):
        await message.answer(
            "❌ Это старое сообщение с оценкой. "
            "Найдите последнее сообщение бота и нажмите кнопку в нём."
        )
        return

    try:
        pending_id = int(payload.get("pending_rating_id"))
        rating_value = int(payload.get("rating"))
    except (TypeError, ValueError):
        await message.answer("❌ Не удалось определить запрос оценки. Используйте новое сообщение.")
        return

    if pending_id <= 0 or rating_value < 1 or rating_value > 5:
        await message.answer("❌ Некорректная оценка")
        return

    async for session in get_session():
        from_user = await get_user_by_vk_id(session, user_vk_id)
        if not from_user:
            await message.answer("❌ Пользователь не найден")
            return

        result = await session.execute(
            select(PendingRating)
            .where(
                PendingRating.id == pending_id,
                PendingRating.from_user_id == from_user.id,
                PendingRating.sent_at.isnot(None),
            )
            .with_for_update()
        )
        pending = result.scalar_one_or_none()

        if not pending:
            await message.answer(
                "❌ Запрос оценки устарел или уже обработан. "
                "Используйте кнопки из актуального сообщения."
            )
            return

        booking = await session.get(Booking, pending.booking_id)
        if not booking:
            logger.error(
                f"Pending rating {pending.id} references missing booking "
                f"{pending.booking_id}"
            )
            await message.answer("❌ Не удалось найти бронирование для этой оценки")
            return

        trip = await session.get(Trip, booking.trip_id)
        if not trip:
            logger.error(
                f"Pending rating {pending.id} references missing trip {booking.trip_id}"
            )
            await message.answer("❌ Не удалось найти поездку для этой оценки")
            return

        # Проверяем, что оценку может поставить только участник бронирования
        # и что получатель действительно является вторым участником.
        if from_user.id == trip.driver_id:
            expected_target_id = booking.passenger_id
        elif from_user.id == booking.passenger_id:
            expected_target_id = trip.driver_id
        else:
            await message.answer("❌ Вы не являетесь участником этой поездки")
            return

        if pending.to_user_id != expected_target_id:
            logger.error(f"Pending rating {pending.id} has an invalid target")
            await message.answer("❌ Некорректный запрос оценки")
            return

        existing = await session.execute(
            select(Rating.id).where(
                Rating.booking_id == booking.id,
                Rating.from_user_id == from_user.id,
            ).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            await session.delete(pending)
            await session.commit()
            await message.answer("❌ Вы уже оценили эту поездку")
            return

        session.add(
            Rating(
                booking_id=booking.id,
                from_user_id=from_user.id,
                to_user_id=expected_target_id,
                value=rating_value,
            )
        )
        await session.delete(pending)
        await session.commit()

        await update_user_rating(session, expected_target_id)

        await message.answer(
            f"✅ Спасибо за оценку! Вы поставили {rating_value}⭐",
            keyboard=main_menu_keyboard()
        )
        logger.info(
            f"Rating {rating_value} from user {from_user.id} "
            f"for booking {booking.id} to user {expected_target_id}"
        )
