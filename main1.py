import multiprocessing
import asyncio
import logging
from vkbottle import Bot
from vkbottle.bot import Message
from config import settings
from db import engine
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
    create_trip_handler, process_route, process_datetime,
    process_seats, process_price, process_comment, process_publish,
    CreateTripState
)
from handlers.search import (
    search_trip_handler, process_search_route, process_search_date,
    process_sort_and_search, handle_search_navigation, handle_search_action,
    SearchState
)
from handlers.my_trips_driver import (
    my_trips_menu_handler, active_trips_handler, delete_trip_handler,
    confirm_delete_trip, incoming_requests_handler, handle_booking_response
)
from handlers.my_bookings_passenger import (
    my_bookings_menu_handler, my_bookings_handler,
    cancel_booking_handler, subscriptions_handler, unsubscribe_handler
)
from handlers.support import support_handler
from handlers.admin import (
    admin_handler, stats_handler, users_list_handler,
    trips_admin_handler, logs_handler
)

def start_scheduler():
    from scheduler_process import scheduler_main
    asyncio.run(scheduler_main())

def safe_delete_ctx(key: str):
    """Безопасное удаление ключа из контекста"""
    try:
        ctx.delete(key)
    except KeyError:
        pass

async def state_router(message: Message):
    """Маршрутизирует сообщения в зависимости от активного состояния"""
    user_id = message.from_id
    
    # Проверяем состояние оценки (рейтинг)
    rating_state = ctx.get(f"rating_state_{user_id}")
    if rating_state is not None:
        logger.info(f"Processing rating state: {rating_state}")
        if rating_state == RatingState.WAITING_RATING:
            await process_rating(message)
            return True
    
    # Проверяем состояния редактирования профиля
    edit_state = ctx.get(f"edit_state_{user_id}")
    if edit_state is not None:
        logger.info(f"Processing edit state: {edit_state}")
        if edit_state == EditProfileState.CHOOSING_FIELD:
            await process_edit_choice(message)
        elif edit_state == EditProfileState.EDITING_NAME:
            await process_edit_name(message)
        elif edit_state == EditProfileState.EDITING_AGE:
            await process_edit_age(message)
        elif edit_state == EditProfileState.EDITING_PHONE:
            await process_edit_phone(message)
        return True
    
    # Проверяем состояния регистрации
    reg_state = ctx.get(f"reg_state_{user_id}")
    if reg_state is not None:
        logger.info(f"Processing reg state: {reg_state}")
        if reg_state == RegistrationState.WAITING_NAME:
            await process_name(message)
        elif reg_state == RegistrationState.WAITING_AGE:
            await process_age(message)
        elif reg_state == RegistrationState.WAITING_GENDER:
            await process_gender(message)
        elif reg_state == RegistrationState.WAITING_PHONE:
            await process_phone(message)
        return True
    
    # Проверяем состояния создания поездки
    create_state = ctx.get(f"create_trip_{user_id}")
    if create_state is not None:
        logger.info(f"Processing create state: {create_state}")
        if create_state == CreateTripState.WAITING_ROUTE:
            await process_route(message)
        elif create_state == CreateTripState.WAITING_DATETIME:
            await process_datetime(message)
        elif create_state == CreateTripState.WAITING_SEATS:
            await process_seats(message)
        elif create_state == CreateTripState.WAITING_PRICE:
            await process_price(message)
        elif create_state == CreateTripState.WAITING_COMMENT:
            await process_comment(message)
        elif create_state == CreateTripState.WAITING_PUBLISH:
            await process_publish(message)
        return True
    
    # Проверяем состояния поиска
    search_state = ctx.get(f"search_state_{user_id}")
    if search_state is not None:
        logger.info(f"Processing search state: {search_state}")
        if search_state == SearchState.WAITING_ROUTE:
            await process_search_route(message)
        elif search_state == SearchState.WAITING_DATE:
            await process_search_date(message)
        elif search_state == SearchState.WAITING_SORT:
            await process_sort_and_search(message)
        return True
    
    return False

async def main():
    logger.add(settings.LOG_FILE, rotation="10 MB", retention="7 days", level="INFO")
    
    # Создаём таблицы
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=settings.VK_GROUP_TOKEN)

    # Точные совпадения
    exact_matches = {
        "Начать": start_handler,
        "Меню": send_main_menu,
        "👤 Профиль": profile_handler,
        "🛡️ Техподдержка": support_handler,
        "🔙 В меню": send_main_menu,
        "🔍 Найти поездку": search_trip_handler,
        "📅 По дате": process_sort_and_search,
        "💰 По цене": process_sort_and_search,
        "⭐ По рейтингу": process_sort_and_search,
        "⬅ Назад": handle_search_navigation,
        "Вперёд ➡": handle_search_navigation,
        "🔔 Подписаться на маршрут": handle_search_action,
        "➕ Создать поездку": create_trip_handler,
        "Да, на стену": process_publish,
        "Только в поиске": process_publish,
        "Пропустить": process_phone,
        "Пропустить комментарий": process_comment,
        "✏️ Редактировать профиль": edit_profile_handler,
        "👤 Изменить имя": process_edit_choice,
        "📅 Изменить возраст": process_edit_choice,
        "📱 Изменить телефон": process_edit_choice,
        "1⭐": process_rating,
        "2⭐": process_rating,
        "3⭐": process_rating,
        "4⭐": process_rating,
        "5⭐": process_rating,
        "📋 Мои поездки": my_trips_menu_handler,
        "🚗 Активные поездки": active_trips_handler,
        "📩 Входящие заявки": incoming_requests_handler,
        "❌ Нет": send_main_menu,
        "📌 Мои бронирования и подписки": my_bookings_menu_handler,
        "📌 Мои бронирования": my_bookings_handler,
        "🔔 Активные подписки": subscriptions_handler,
        "🔐 Админ-панель": admin_handler,
        "📊 Статистика": stats_handler,
        "👥 Пользователи": users_list_handler,
        "🚗 Поездки": trips_admin_handler,
        "📋 Логи": logs_handler,
    }
    
    for text, handler in exact_matches.items():
        bot.on.message(text=text)(handler)

    # Самый последний обработчик
    @bot.on.message()
    async def catch_all(message: Message):
        user_id = message.from_id
        text = message.text.strip()
        
        logger.info(f"CATCH_ALL: '{text}' from {user_id}")
        
        # Действия поиска
        if "💬 Обсудить" in text or "✅ Бронировать" in text:
            logger.info("→ handle_search_action")
            await handle_search_action(message)
            return
        
        # Действия водителя
        if "🗑 Удалить" in text:
            await delete_trip_handler(message)
            return
        if "✅ Да, удалить" in text:
            await confirm_delete_trip(message)
            return
        if "✅ Принять" in text or "❌ Отклонить" in text:
            await handle_booking_response(message)
            return
        
        # Действия пассажира
        if "❌ Отменить" in text:
            await cancel_booking_handler(message)
            return
        if "🔕 Отписаться" in text:
            await unsubscribe_handler(message)
            return
        
        # Очищаем старые результаты поиска при любом другом сообщении
        safe_delete_ctx(f"search_results_{user_id}")
        
        # Пробуем обработать состояние
        handled = await state_router(message)
        
        if not handled:
            await send_main_menu(message)

    # Запуск планировщика
    scheduler_proc = multiprocessing.Process(target=start_scheduler)
    scheduler_proc.start()

    try:
        logger.info("Бот запущен")
        await bot.run_polling()
    finally:
        scheduler_proc.terminate()
        scheduler_proc.join()
        logger.info("Бот остановлен")

if __name__ == "__main__":
    asyncio.run(main())