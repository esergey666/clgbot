from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.config import BotConfig
from bot.keyboards import cabinet_keyboard, label_prices_text, label_type_keyboard, user_home_keyboard
from bot.pricing import DEFAULT_GENERATION_PRICES
from bot.services.access import AccessService
from bot.states import LabelForm
from bot.ui import replace_ui_message, send_ui_message
from bot.version import APP_VERSION

router = Router()


def _get_dmtx_status() -> str:
    try:
        from pylibdmtx.pylibdmtx import encode  # noqa: F401
    except Exception as error:
        return f"not available ({type(error).__name__}: {error})"
    return "available"


def _record_user(config: BotConfig, user: User | None) -> None:
    if user is None:
        return
    AccessService(config.access_users_path).record_user_profile(
        user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )


def _has_access(message: Message, config: BotConfig) -> bool:
    return message.from_user is not None and AccessService(config.access_users_path).has_access(
        message.from_user.id,
        config.admin_ids,
    )


def _label_type_keyboard(config: BotConfig):
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    return label_type_keyboard(prices)


def _generation_prices_text(config: BotConfig) -> str:
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    return label_prices_text(prices)


def _cabinet_text(user_id: int, config: BotConfig) -> str:
    access = AccessService(config.access_users_path)
    user_label = access.format_user_label(user_id)
    if user_id in config.admin_ids:
        access_text = "администратор"
        balance_text = "без ограничений"
    elif access.has_permanent_access(user_id, config.admin_ids):
        access_text = "постоянный доступ"
        balance_text = "без ограничений"
    else:
        balance = access.get_balance(user_id)
        access_text = "доступ по балансу" if balance > 0 else "нет активного доступа"
        balance_text = str(balance)

    return (
        "Личный кабинет\n\n"
        f"Telegram ID: <code>{user_id}</code>\n"
        f"Пользователь: <b>{user_label}</b>\n"
        f"Статус: <b>{access_text}</b>\n"
        f"Баланс: <b>{balance_text}</b>"
    )


async def _show_home(message: Message, state: FSMContext, config: BotConfig) -> None:
    _record_user(config, message.from_user)
    await state.set_state(LabelForm.waiting_for_label_type)
    has_access = _has_access(message, config)
    status_text = (
        "Доступ активирован — можно создавать файлы."
        if has_access
        else "Можно бесплатно смотреть защищённые примеры.\nДля генерации файла потребуется активировать доступ."
    )
    await send_ui_message(
        message,
        state,
        f"Главное меню\n\n{status_text}\n\nВыберите действие:",
        reply_markup=user_home_keyboard(),
    )


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    await _show_home(message, state, config)


@router.message(Command("id"))
async def id_command(message: Message, config: BotConfig) -> None:
    _record_user(config, message.from_user)
    if message.from_user is None:
        return
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("version"))
async def version_command(message: Message, config: BotConfig) -> None:
    _record_user(config, message.from_user)
    await message.answer(
        f"Bot version: <code>{APP_VERSION}</code>\n"
        f"libdmtx: <code>{_get_dmtx_status()}</code>"
    )


@router.callback_query(F.data == "user:home")
async def user_home(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    _record_user(config, callback.from_user)
    if callback.message is None:
        await callback.answer()
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    has_access = AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids)
    status_text = (
        "Доступ активирован — можно создавать файлы."
        if has_access
        else "Можно бесплатно смотреть защищённые примеры.\nДля генерации файла потребуется активировать доступ."
    )
    await replace_ui_message(
        callback,
        state,
        f"Главное меню\n\n{status_text}\n\nВыберите действие:",
        reply_markup=user_home_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "user:generate")
async def user_generate(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    _record_user(config, callback.from_user)
    has_access = AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids)
    await state.set_state(LabelForm.waiting_for_label_type)
    if callback.message is not None:
        if has_access:
            access_note = "Выберите, что нужно сгенерировать:"
        else:
            access_note = (
                "Выберите позицию, чтобы посмотреть защищённый пример.\n"
                "Для создания файла нужен активный доступ."
            )
        await replace_ui_message(
            callback,
            state,
            f"{access_note}\n\n"
            "Стоимость генерации:\n"
            f"{_generation_prices_text(config)}",
            reply_markup=_label_type_keyboard(config),
        )
    await callback.answer()


@router.callback_query(F.data == "user:cabinet")
async def user_cabinet(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    _record_user(config, callback.from_user)
    await replace_ui_message(
        callback,
        state,
        _cabinet_text(callback.from_user.id, config),
        reply_markup=cabinet_keyboard(),
    )
    await callback.answer()
