from vkbottle.bot import Message
from vkbottle import Keyboard, Text, KeyboardButtonColor

SUPPORT_TEXT = """
🛡️ Правила безопасной поездки:

1. Договаривайтесь о деталях поездки заранее
2. Обменивайтесь контактами только через бота
3. Проверяйте рейтинг попутчика перед поездкой
4. Сообщайте близким о маршруте и времени поездки
5. При возникновении проблем обращайтесь в техподдержку

📞 Контакты техподдержки:
• Группа ВК: vk.com/poputchik_support
• Email: support@poputchik.ru
• Время работы: 9:00 - 21:00 МСК

С уважением, команда «Попутчик» 🚗
"""

async def support_handler(message: Message):
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
    await message.answer(SUPPORT_TEXT, keyboard=keyboard.get_json())