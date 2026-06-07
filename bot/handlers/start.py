from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from bot.config import BotConfig
from bot.keyboards import access_denied_keyboard, cabinet_keyboard, label_type_keyboard, user_home_keyboard
from bot.services.access import AccessService
from bot.states import LabelForm
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
    if not _has_access(message, config):
        await message.answer(
            "Доступ не активирован.\n\n"
            "Напишите администратору, чтобы он выдал баланс на ваш Telegram ID.",
            reply_markup=access_denied_keyboard(),
        )
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await message.answer(
        "Главное меню\n\nВыберите действие:",
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

    if not AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids):
        await callback.message.answer(
            "Доступ не активирован.\n\nНапишите администратору, чтобы он выдал баланс на ваш Telegram ID.",
            reply_markup=access_denied_keyboard(),
        )
        await callback.answer()
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await callback.message.answer("Главное меню\n\nВыберите действие:", reply_markup=user_home_keyboard())
    await callback.answer()


@router.callback_query(F.data == "user:generate")
async def user_generate(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    _record_user(config, callback.from_user)
    if not AccessService(config.access_users_path).has_access(callback.from_user.id, config.admin_ids):
        await callback.answer("Нет активного доступа", show_alert=True)
        if callback.message is not None:
            await callback.message.answer(
                "Доступ не активирован. Напишите администратору, чтобы он выдал баланс.",
                reply_markup=access_denied_keyboard(),
            )
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    if callback.message is not None:
        await callback.message.answer("Что нужно сгенерировать?", reply_markup=label_type_keyboard())
    await callback.answer()


@router.callback_query(F.data == "user:cabinet")
async def user_cabinet(callback: CallbackQuery, config: BotConfig) -> None:
    _record_user(config, callback.from_user)
    if callback.message is not None:
        await callback.message.answer(_cabinet_text(callback.from_user.id, config), reply_markup=cabinet_keyboard())
    await callback.answer()
