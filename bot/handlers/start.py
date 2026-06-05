from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import BotConfig
from bot.keyboards import access_denied_keyboard, cabinet_keyboard, label_type_keyboard, user_back_keyboard, user_home_keyboard
from bot.services.access import AccessService
from bot.states import LabelForm

router = Router()


def _has_access(message: Message, config: BotConfig) -> bool:
    return message.from_user is not None and AccessService(config.access_users_path).has_access(
        message.from_user.id,
        config.admin_ids,
    )


def _cabinet_text(user_id: int, config: BotConfig) -> str:
    access = AccessService(config.access_users_path)
    if user_id in config.admin_ids:
        access_text = "администратор"
        balance_text = "без ограничений"
    elif access.has_permanent_access(user_id, config.admin_ids):
        access_text = "постоянный доступ"
        balance_text = "без ограничений"
    else:
        balance = access.get_balance(user_id)
        access_text = "доступ по ключу" if balance > 0 else "нет активного доступа"
        balance_text = str(balance)

    return (
        "Личный кабинет\n\n"
        f"Telegram ID: <code>{user_id}</code>\n"
        f"Статус: <b>{access_text}</b>\n"
        f"Баланс: <b>{balance_text}</b>"
    )


async def _show_home(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _has_access(message, config):
        await message.answer(
            "Доступ не активирован.\n\n"
            "Нажмите кнопку ниже и отправьте ключ, который выдал администратор.",
            reply_markup=access_denied_keyboard(),
        )
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await message.answer(
        "Главное меню\n\nВыберите действие:",
        reply_markup=user_home_keyboard(),
    )


async def _activate_access_key(message: Message, state: FSMContext, config: BotConfig, raw_key: str) -> None:
    if message.from_user is None:
        return

    balance = AccessService(config.access_users_path).activate_key(message.from_user.id, raw_key)
    if balance is None:
        await message.answer("Ключ не найден или уже использован.")
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await message.answer(
        "Ключ активирован.\n"
        f"Баланс: <b>{balance}</b>\n\n"
        "Теперь можно создавать файлы.",
        reply_markup=user_home_keyboard(),
    )


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    await _show_home(message, state, config)


@router.message(Command("id"))
async def id_command(message: Message) -> None:
    if message.from_user is None:
        return

    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("key"))
async def key_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    if message.text is None:
        await message.answer("Отправьте ключ после команды. Например: <code>/key KEY-ABCD-1234-EFGH</code>")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Отправьте ключ после команды. Например: <code>/key KEY-ABCD-1234-EFGH</code>")
        return

    await _activate_access_key(message, state, config, parts[1])


@router.callback_query(F.data == "user:home")
async def user_home(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if callback.message is None:
        await callback.answer()
        return

    if not AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids):
        await callback.message.answer(
            "Доступ не активирован.\n\nАктивируйте ключ, чтобы открыть генерацию.",
            reply_markup=access_denied_keyboard(),
        )
        await callback.answer()
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await callback.message.answer("Главное меню\n\nВыберите действие:", reply_markup=user_home_keyboard())
    await callback.answer()


@router.callback_query(F.data == "user:generate")
async def user_generate(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids):
        await callback.answer("Нет активного доступа", show_alert=True)
        if callback.message is not None:
            await callback.message.answer("Сначала активируйте ключ доступа.", reply_markup=access_denied_keyboard())
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    if callback.message is not None:
        await callback.message.answer("Что нужно сгенерировать?", reply_markup=label_type_keyboard())
    await callback.answer()


@router.callback_query(F.data == "user:cabinet")
async def user_cabinet(callback: CallbackQuery, config: BotConfig) -> None:
    if callback.message is not None:
        await callback.message.answer(_cabinet_text(callback.from_user.id, config), reply_markup=cabinet_keyboard())
    await callback.answer()


@router.callback_query(F.data == "user:activate_key")
async def user_activate_key(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LabelForm.waiting_for_access_key)
    if callback.message is not None:
        await callback.message.answer(
            "Отправьте ключ доступа одним сообщением.\n"
            "Пример: <code>KEY-ABCD-1234-EFGH</code>",
            reply_markup=user_back_keyboard(),
        )
    await callback.answer()


@router.message(LabelForm.waiting_for_access_key)
async def access_key_message(message: Message, state: FSMContext, config: BotConfig) -> None:
    if message.text is None:
        await message.answer("Отправьте ключ текстом.", reply_markup=user_back_keyboard())
        return

    await _activate_access_key(message, state, config, message.text)


@router.message(F.text.regexp(r"^KEY-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4}$"))
async def plain_key_message(message: Message, state: FSMContext, config: BotConfig) -> None:
    if message.text is None:
        return

    await _activate_access_key(message, state, config, message.text)
