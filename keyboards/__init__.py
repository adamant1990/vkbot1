from vkbottle import Keyboard, Text, KeyboardButtonColor

def main_menu_keyboard():
    keyboard = Keyboard(inline=False)
    keyboard.add(Text("🔍 Найти поездку"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("➕ Создать поездку"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📋 Мои поездки"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("📌 Мои бронирования и подписки"), KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("👤 Профиль"), KeyboardButtonColor.SECONDARY)
    keyboard.add(Text("🛡️ Техподдержка"), KeyboardButtonColor.SECONDARY)
    return keyboard.get_json()

def gender_keyboard():
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("Мужской"), KeyboardButtonColor.PRIMARY)
    keyboard.add(Text("Женский"), KeyboardButtonColor.PRIMARY)
    return keyboard.get_json()

def yes_no_keyboard():
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("Да"), KeyboardButtonColor.POSITIVE)
    keyboard.add(Text("Нет"), KeyboardButtonColor.NEGATIVE)
    return keyboard.get_json()

def back_to_menu_button():
    keyboard = Keyboard(inline=True)
    keyboard.add(Text("🔙 В меню"), KeyboardButtonColor.SECONDARY)
    return keyboard.get_json()

def pagination_keyboard(page, total_pages):
    keyboard = Keyboard(inline=True)
    if page > 1:
        keyboard.add(Text("⬅ Назад"), KeyboardButtonColor.PRIMARY)
    if page < total_pages:
        keyboard.add(Text("Вперёд ➡"), KeyboardButtonColor.PRIMARY)
    return keyboard.get_json()