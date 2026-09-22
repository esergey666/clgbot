from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def keyboard(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=title, callback_data=data) for title, data in row]
        for row in rows])


def cancel_keyboard():
    return keyboard([('❌ Отмена', 'fr:cancel')])


def date_keyboard():
    return keyboard([('📅 Сегодня', 'fr:today')], [('❌ Отмена', 'fr:cancel')])


def items_keyboard(count):
    rows = []
    if count < 20:
        rows.append([('➕ Добавить товар', 'fr:add')])
    rows.extend([[('✅ Закончить', 'fr:finish')], [('❌ Отмена', 'fr:cancel')]])
    return keyboard(*rows)


def confirm_keyboard():
    return keyboard([('✅ Создать чек', 'fr:create')],
                    [('✏️ Изменить данные', 'fr:edit')], [('❌ Отмена', 'fr:cancel')])
