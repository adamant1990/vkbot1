import asyncio
import logging
from vkbottle import Bot
from vkbottle.bot import Message
from config import settings
from db import engine, get_session, get_redis, close_db, close_redis
from models import Base
from loguru import logger

# Отключаем DEBUG логи
logging.getLogger("vkbottle.dispatch").setLevel(logging.WARNING)
logging.getLogger("vkbottle.polling").setLevel(logging.INFO)

# Импорты обработчиков
from handlers.menu import (
    start_handler, send_main_menu, ctx, RegistrationState, EditProfileState, RatingState,
    process_name, process_age, process_gender, process_phone,
    edit_profile_handler, process_edit_choice, process_edit_name,
    process_edit_age, process_edit_phone, process_rating
)
from handlers.profile import profile_handler
from handlers.trips import (
    create_trip_handler, process_route, process_calendar_date,
    process_manual_date, process_time,
    process_seats, process_price, process_comment, process_publish,
    CreateTripState
)
from handlers.search import (
    search_trip_handler, process_search_route, process_search_calendar_date,
    process_search_manual_date,
    process_sort_and_search, handle_search_navigation, handle_search_action,
    SearchState
)
from handlers.my_trips_driver import (
    my_trips_menu_handler, active_trips_handler, delete_trip_handler,
    confirm_delete_trip, incoming_requests_handler, handle_booking_response
)
from handlers.my_bookings_passenger import (
    my_bookings_menu_handler, my_bookings_handler,
    cancel_booking_handler, confirm_cancel_booking,
    subscriptions_handler, unsubscribe_handler
)
from handlers.support import support_handler
from handlers.admin import (
    admin_handler, stats_handler, users_list_handler,
    trips_admin_handler, logs_handler, price_settings_handler,
    change_tariff_handler, change_coefficient_handler, change_angle_handler,
    process_new_tariff, process_new_coefficient, process_new_angle,
    broadcast_handler, process_broadcast,
    users_management_handler, users_navigation_handler,
    search_users_handler, process_users_search,
    ban_user_handler, change_rating_handler, process_change_rating,
    reset_rating_handler
)

async def safe_delete_ctx(key: str):
    """Безопасное удаление ключа из контекста (Redis)"""
    try:
        await ctx.delete(key)
    except Exception:
        pass

async def run_scheduler():
    """Запускает планировщик как фоновую asyncio-задачу с защитой от падений"""
    from scheduler_process import complete_trips_and_request_ratings
    logger.info("Планировщик запущен (фоновая задача)")
    while True:
        await asyncio.sleep(1800)
        try:
            await complete_trips_and_request_ratings()
        except Exception as e:
            logger.error(f"Ошибка планировщика: {e}")
            await asyncio.sleep(300)

async def state_router(message: Message):
    """Маршрутизирует сообщения в зависимости от активного состояния"""
    user_id = message.from_id
    
    try:
        if await ctx.get(f"admin_users_search_input_{user_id}"):
            await process_users_search(message)
            return True
        
        if await ctx.get(f"admin_change_rating_{user_id}"):
            await process_change_rating(message)
            return True
        
        if await ctx.get(f"admin_broadcast_{user_id}"):
            await process_broadcast(message)
            return True
        
        if await ctx.get(f"admin_change_tariff_{user_id}"):
            await process_new_tariff(message)
            return True
        
        if await ctx.get(f"admin_change_coefficient_{user_id}"):
            await process_new_coefficient(message)
            return True
        
        if await ctx.get(f"admin_change_angle_{user_id}"):
            await process_new_angle(message)
            return True
        
        rating_state = await ctx.get(f"rating_state_{user_id}")
        if rating_state is not None:
            logger.info(f"Processing rating state: {rating_state}")
            if rating_state == RatingState.WAITING_RATING.value:
                await process_rating(message)
                return True
        
        edit_state = await ctx.get(f"edit_state_{user_id}")
        if edit_state is not None:
            logger.info(f"Processing edit state: {edit_state}")
            if edit_state == EditProfileState.CHOOSING_FIELD.value:
                await process_edit_choice(message)
            elif edit_state == EditProfileState.EDITING_NAME.value:
                await process_edit_name(message)
            elif edit_state == EditProfileState.EDITING_AGE.value:
                await process_edit_age(message)
            elif edit_state == EditProfileState.EDITING_PHONE.value:
                await process_edit_phone(message)
            return True
        
        reg_state = await ctx.get(f"reg_state_{user_id}")
        if reg_state is not None:
            logger.info(f"Processing reg state: {reg_state}")
            if reg_state == RegistrationState.WAITING_NAME.value:
                await process_name(message)
            elif reg_state == RegistrationState.WAITING_AGE.value:
                await process_age(message)
            elif reg_state == RegistrationState.WAITING_GENDER.value:
                await process_gender(message)
            elif reg_state == RegistrationState.WAITING_PHONE.value:
                await process_phone(message)
            return True
        
        create_state = await ctx.get(f"create_trip_{user_id}")
        if create_state is not None:
            logger.info(f"Processing create state: {create_state!r}, type: {type(create_state).__name__}, WAITING_ROUTE.value={CreateTripState.WAITING_ROUTE.value!r}, equal: {create_state == CreateTripState.WAITING_ROUTE.value}")
            if create_state == CreateTripState.WAITING_ROUTE.value:
                logger.info("Calling process_route...")
                await process_route(message)
            elif create_state == CreateTripState.WAITING_DATE.value:
                await process_calendar_date(message)
            elif create_state == CreateTripState.WAITING_MANUAL_DATE.value:
                await process_manual_date(message)
            elif create_state == CreateTripState.WAITING_TIME.value:
                await process_time(message)
            elif create_state == CreateTripState.WAITING_SEATS.value:
                await process_seats(message)
            elif create_state == CreateTripState.WAITING_PRICE.value:
                await process_price(message)
            elif create_state == CreateTripState.WAITING_COMMENT.value:
                await process_comment(message)
            elif create_state == CreateTripState.WAITING_PUBLISH.value:
                await process_publish(message)
            else:
                logger.warning(f"Unknown create state: {create_state}")
            return True
        
        search_state = await ctx.get(f"search_state_{user_id}")
        if search_state is not None:
            logger.info(f"Processing search state: {search_state}")
            if search_state == SearchState.WAITING_ROUTE.value:
                await process_search_route(message)
            elif search_state == SearchState.WAITING_DATE.value:
                await process_search_calendar_date(message)
            elif search_state == SearchState.WAITING_MANUAL_DATE.value:
                await process_search_manual_date(message)
            elif search_state == SearchState.WAITING_SORT.value:
                await process_sort_and_search(message)
            return True
        
        return False
    except Exception as e:
        logger.error(f"state_router error for user {user_id}: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка. Попробуйте ещё раз или нажмите 'Начать'.")
        return True

async def main():
    logger.add(settings.LOG_FILE, rotation="10 MB", retention="7 days", level="INFO")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis подключён успешно")
    except Exception as e:
        logger.error(f"Redis недоступен: {e}")
        logger.warning("Бот запущен без Redis — состояния будут теряться при перезапуске")

    bot = Bot(token=settings.VK_GROUP_TOKEN)

    exact_matches = {
        "Начать": start_handler,
        "Меню": send_main_menu,
        "👤 Профиль": profile_handler,
        "🛡️ Техподдержка": support_handler,
        "🔙 В меню": send_main_menu,
        "🔙 В админ-панель": admin_handler,
        "🔙 К настройкам": price_settings_handler,
        "🔍 Найти поездку": search_trip_handler,
        "📅 По дате": process_sort_and_search,
        "💰 По цене": process_sort_and_search,
        "⭐ По рейтингу": process_sort_and_search,
        "⬅ Назад": users_navigation_handler,
        "Вперёд ➡": users_navigation_handler,
        "🔔 Подписаться на маршрут": handle_search_action,
        "➕ Создать поездку": create_trip_handler,
        "Да, на стену": process_publish,
        "Только в поиске": process_publish,
        "Пропустить": process_phone,
        "Пропустить комментарий": process_comment,
        "✅ Подтвердить": process_price,
        "✏️ Своя цена": process_price,
        "📆 Другая дата": process_calendar_date,
        "🔙 Отмена": process_calendar_date,
        "✏️ Редактировать профиль": edit_profile_handler,
        "👤 Изменить имя": process_edit_choice,
        "📅 Изменить возраст": process_edit_choice,
        "📱 Изменить телефон": process_edit_choice,
        "1⭐": process_rating,
        "2⭐": process_rating,
        "3⭐": process_rating,
        "4⭐": process_rating,
        "5⭐": process_rating,
        "🚗 ЛК Водителя": my_trips_menu_handler,
        "🚗 Активные поездки": active_trips_handler,
        "📩 Входящие заявки": incoming_requests_handler,
        "❌ Нет": send_main_menu,
        "🧑 ЛК Пассажира": my_bookings_menu_handler,
        "📌 Мои бронирования": my_bookings_handler,
        "🔔 Активные подписки": subscriptions_handler,
        "🔐 Админ-панель": admin_handler,
        "📊 Статистика": stats_handler,
        "👥 Пользователи": users_list_handler,
        "🚗 Поездки": trips_admin_handler,
        "👥 Рейтинги": users_management_handler,
        "⚙️ Настройки": price_settings_handler,
        "✏️ Изменить тариф": change_tariff_handler,
        "📐 Изменить коэффициент": change_coefficient_handler,
        "🧭 Изменить макс. угол": change_angle_handler,
        "📢 Рассылка": broadcast_handler,
        "📋 Логи": logs_handler,
        "🔍 Поиск": search_users_handler,
    }
    
    for text, handler in exact_matches.items():
        bot.on.message(text=text)(handler)

    @bot.on.message()
    async def catch_all(message: Message):
        user_id = message.from_id
        text = message.text.strip()
        
        logger.info(f"CATCH_ALL: '{text}' from {user_id}")
        
        if text == "!debug":
            user = None
            async for session in get_session():
                from utils.db_utils import get_user_by_vk_id
                user = await get_user_by_vk_id(session, user_id)
            
            info = f"🆔 Ваш ID: {user_id}\n"
            info += f"✅ В списке админов: {user_id in settings.admin_ids_list}\n"
            info += f"📋 Список админов: {settings.admin_ids_list}\n"
            info += f"👤 Зарегистрирован: {user is not None}"
            if user:
                info += f"\n📝 Имя: {user.first_name} {user.last_name}"
            await message.answer(info)
            return
        
        if text == "!admin" or text == "/admin":
            await admin_handler(message)
            return
        
        if "Забанить" in text or "Разбанить" in text:
            await ban_user_handler(message)
            return
        if "Рейтинг" in text and "⭐" in text:
            await change_rating_handler(message)
            return
        if "Сбросить" in text:
            await reset_rating_handler(message)
            return
        
        if "Обсудить" in text or "Бронировать" in text:
            logger.info("→ handle_search_action")
            await handle_search_action(message)
            return
        
        if "Удалить" in text and "Да" not in text and "⚠️" not in text:
            await delete_trip_handler(message)
            return
        if "Да, удалить" in text:
            await confirm_delete_trip(message)
            return
        if "⚠️ Да, отменить" in text:
            await confirm_cancel_booking(message)
            return
        if "Принять" in text or "Отклонить" in text:
            await handle_booking_response(message)
            return
        
        if "Отменить" in text and "⚠️" not in text:
            await cancel_booking_handler(message)
            return
        if "Отписаться" in text:
            await unsubscribe_handler(message)
            return
        
        await safe_delete_ctx(f"search_results_{user_id}")
        
        handled = await state_router(message)
        
        if not handled:
            await send_main_menu(message)

    scheduler_task = asyncio.create_task(run_scheduler())

    try:
        logger.info("Бот запущен")
        await bot.run_polling()
    except asyncio.CancelledError:
        logger.info("Бот получил сигнал отмены")
    finally:
        logger.info("Остановка бота...")
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await close_db()
        await close_redis()
        logger.info("Бот остановлен корректно")

if __name__ == "__main__":
    asyncio.run(main())
