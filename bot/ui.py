from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message


LAST_UI_MESSAGE_ID_KEY = "last_ui_message_id"


async def _remember_ui_message(state: FSMContext, message_id: int) -> None:
    await state.update_data(**{LAST_UI_MESSAGE_ID_KEY: message_id})


async def delete_last_ui_message(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    message_id = data.get(LAST_UI_MESSAGE_ID_KEY)
    if not message_id:
        return

    try:
        await message.bot.delete_message(message.chat.id, int(message_id))
    except TelegramBadRequest:
        pass


async def send_ui_message(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> Message:
    await delete_last_ui_message(message, state)
    sent = await message.answer(text, reply_markup=reply_markup)
    await _remember_ui_message(state, sent.message_id)
    return sent


async def replace_ui_message(
    callback: CallbackQuery,
    state: FSMContext,
    text: str,
    reply_markup=None,
) -> Message | None:
    if callback.message is None:
        return None

    try:
        edited = await callback.message.edit_text(text, reply_markup=reply_markup)
        await _remember_ui_message(state, callback.message.message_id)
        return edited if isinstance(edited, Message) else callback.message
    except TelegramBadRequest:
        return await send_ui_message(callback.message, state, text, reply_markup=reply_markup)
