from vkbottle.bot import Message
from keyboards import main_menu_keyboard
from db import get_session
from utils.db_utils import get_user_by_vk_id
from vkbottle import Keyboard, Text, KeyboardButtonColor

async def profile_handler(message: Message):
    async for session in get_session():
        user = await get_user_by_vk_id(session, message.from_id)
        
        if not user:
            await message.answer("❌ Сначала зарегистрируйтесь! Отправьте 'Начать'")
            return
        
        rating_str = f"{user.rating:.1f}⭐ ({user.rating_count} оценок)" if user.rating else "Нет оценок"
        
        profile_text = (
            f"👤 Профиль\n\n"
            f"Имя: {user.first_name} {user.last_name}\n"
            f"Возраст: {user.age}\n"
            f"Пол: {user.gender}\n"
            f"Телефон: {user.phone or 'Не указан'}\n"
            f"Рейтинг: {rating_str}\n"
        )
        
        # Кнопки профиля
        keyboard = Keyboard(inline=False)
        keyboard.add(Text("✏️ Редактировать профиль"), KeyboardButtonColor.PRIMARY)
        keyboard.row()
        keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
        
        await message.answer(profile_text, keyboard=keyboard.get_json())