from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import BotConfig
from bot.keyboards import (
    CLG2026_LABEL_TYPE,
    LABEL_TYPE_TITLES,
    MAIN_LABEL_TYPE,
    PRICE_TAG_LABEL_TYPE,
    RECEIPT_LABEL_TYPE,
    access_keys_keyboard,
    access_users_keyboard,
    admin_back_keyboard,
    admin_panel_keyboard,
)
from bot.pricing import DEFAULT_GENERATION_PRICES, PRICE_LABEL_ORDER
from bot.services import AccessService
from bot.states import AdminForm

router = Router()


PRICE_INPUT_ALIASES = {
    "40": MAIN_LABEL_TYPE,
    "main": MAIN_LABEL_TYPE,
    "45": CLG2026_LABEL_TYPE,
    "clg2026": CLG2026_LABEL_TYPE,
    "price": PRICE_TAG_LABEL_TYPE,
    "ценник": PRICE_TAG_LABEL_TYPE,
    "check": RECEIPT_LABEL_TYPE,
    "receipt": RECEIPT_LABEL_TYPE,
    "чек": RECEIPT_LABEL_TYPE,
}


def _is_owner(message: Message, config: BotConfig) -> bool:
    return message.from_user is not None and message.from_user.id in config.admin_ids


def _is_owner_callback(callback: CallbackQuery, config: BotConfig) -> bool:
    return callback.from_user.id in config.admin_ids


def _parse_user_id(text: str) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError("Отправьте Telegram ID числом. Например: 123456789")
    return int(value)


def _parse_balance(text: str) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError("Отправьте сумму баланса числом. Например: 100")

    balance = int(value)
    if balance <= 0:
        raise ValueError("Баланс должен быть больше нуля.")

    return balance


def _format_prices(config: BotConfig) -> str:
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    return "\n".join(
        f"{LABEL_TYPE_TITLES[label_type]}: <b>{prices[label_type]}</b>"
        for label_type in PRICE_LABEL_ORDER
    )


def _parse_generation_prices(text: str, config: BotConfig) -> dict[str, int]:
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    parts = [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]
    if not parts:
        raise ValueError("Отправьте цены в формате: 40=10, 45=15, price=5, check=20")

    for part in parts:
        if "=" not in part:
            raise ValueError(f"Нет знака '=' в части: {part}")
        raw_key, raw_value = [item.strip() for item in part.split("=", maxsplit=1)]
        label_type = PRICE_INPUT_ALIASES.get(raw_key.lower())
        if label_type is None:
            raise ValueError(f"Неизвестный тип: {raw_key}")
        if not raw_value.isdigit():
            raise ValueError(f"Цена для {raw_key} должна быть числом.")
        price = int(raw_value)
        if price <= 0:
            raise ValueError(f"Цена для {raw_key} должна быть больше нуля.")
        prices[label_type] = price

    return prices


def _admin_panel_text(config: BotConfig) -> str:
    access = AccessService(config.access_users_path)
    permanent_count = len(access.list_user_ids())
    balance_count = len([balance for balance in access.list_balances().values() if balance > 0])
    key_count = len(access.list_keys())

    return (
        "Админ-панель\n\n"
        f"Постоянный доступ: <b>{permanent_count}</b>\n"
        f"Пользователи с балансом: <b>{balance_count}</b>\n"
        f"Активные ключи: <b>{key_count}</b>\n\n"
        "Выберите действие:"
    )


@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return

    await state.clear()
    await message.answer(_admin_panel_text(config), reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message is not None:
        await callback.message.answer(_admin_panel_text(config), reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:create_key")
async def admin_create_key(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_for_key_generations)
    if callback.message is not None:
        await callback.message.answer(
            "Новый ключ доступа\n\n"
            "Какой баланс должен быть в ключе?\n"
            "Например: <code>100</code>",
            reply_markup=admin_back_keyboard(),
        )
    await callback.answer()


@router.message(AdminForm.waiting_for_key_generations)
async def admin_save_key(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return

    if message.text is None:
        await message.answer("Отправьте сумму баланса числом.")
        return

    try:
        balance = _parse_balance(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    key = AccessService(config.access_users_path).create_key(balance)
    await state.clear()
    await message.answer(
        "Ключ создан:\n"
        f"<code>{key}</code>\n\n"
        f"Баланс: <b>{balance}</b>.\n"
        "Отправьте этот ключ пользователю. После активации ключ сгорит.",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin:prices")
async def admin_prices(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_for_generation_prices)
    if callback.message is not None:
        await callback.message.answer(
            "Цены генераций\n\n"
            f"{_format_prices(config)}\n\n"
            "Отправьте новые цены одной строкой. Можно менять все или часть:\n"
            "<code>40=10, 45=15, price=5, check=20</code>\n\n"
            "Обозначения: <code>40</code> бирка 40мм, <code>45</code> бирка 45мм, "
            "<code>price</code> ценник, <code>check</code> чек.",
            reply_markup=admin_back_keyboard(),
        )
    await callback.answer()


@router.message(AdminForm.waiting_for_generation_prices)
async def admin_save_prices(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return

    if message.text is None:
        await message.answer("Отправьте цены текстом. Пример: <code>40=10, 45=15, price=5, check=20</code>")
        return

    try:
        prices = _parse_generation_prices(message.text, config)
    except ValueError as error:
        await message.answer(str(error))
        return

    AccessService(config.access_users_path).set_generation_prices(prices)
    await state.clear()
    await message.answer(
        "Цены сохранены:\n\n"
        f"{_format_prices(config)}",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(F.data == "admin:add_user")
async def admin_add_user(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_for_user_id)
    if callback.message is not None:
        await callback.message.answer(
            "Постоянный доступ\n\n"
            "Отправьте Telegram ID пользователя, которому нужно выдать доступ без лимита баланса.",
            reply_markup=admin_back_keyboard(),
        )
    await callback.answer()


@router.message(AdminForm.waiting_for_user_id)
async def admin_save_user(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return

    if message.text is None:
        await message.answer("Отправьте Telegram ID числом.")
        return

    try:
        user_id = _parse_user_id(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    access = AccessService(config.access_users_path)
    was_added = access.add_user(user_id)
    await state.clear()

    if was_added:
        await message.answer(f"Доступ выдан пользователю <code>{user_id}</code>.", reply_markup=admin_panel_keyboard())
    else:
        await message.answer(f"Пользователь <code>{user_id}</code> уже был в списке.", reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin:list_users")
async def admin_list_users(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    access = AccessService(config.access_users_path)
    user_ids = access.list_user_ids()
    balances = access.list_balances()
    if callback.message is not None:
        lines = [f"<code>{user_id}</code> — постоянный доступ" for user_id in user_ids]
        quota_user_ids = [
            user_id
            for user_id, balance in balances.items()
            if balance > 0 and user_id not in user_ids
        ]
        lines.extend(
            f"<code>{user_id}</code> — баланс: <b>{balance}</b>"
            for user_id, balance in balances.items()
            if balance > 0 and user_id not in user_ids
        )

        if lines:
            await callback.message.answer(
                "Пользователи с доступом:\n" + "\n".join(lines),
                reply_markup=access_users_keyboard(user_ids, quota_user_ids),
            )
        else:
            await callback.message.answer("Список пользователей пуст.", reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:list_keys")
async def admin_list_keys(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    keys = AccessService(config.access_users_path).list_keys()
    if callback.message is not None:
        if keys:
            lines = [f"<code>{key}</code> — баланс <b>{balance}</b>" for key, balance in keys.items()]
            await callback.message.answer(
                "Активные ключи:\n" + "\n".join(lines),
                reply_markup=access_keys_keyboard(list(keys)),
            )
        else:
            await callback.message.answer("Активных ключей нет.", reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:remove_user:"))
async def admin_remove_user(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int((callback.data or "").rsplit(":", maxsplit=1)[1])
    was_removed = AccessService(config.access_users_path).remove_user(user_id)
    user_ids = AccessService(config.access_users_path).list_user_ids()

    if callback.message is not None:
        text = f"Доступ пользователя <code>{user_id}</code> удалён." if was_removed else "Пользователь не найден."
        await callback.message.answer(text, reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:clear_quota:"))
async def admin_clear_quota(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int((callback.data or "").rsplit(":", maxsplit=1)[1])
    was_removed = AccessService(config.access_users_path).clear_quota(user_id)

    if callback.message is not None:
        text = f"Баланс пользователя <code>{user_id}</code> сброшен." if was_removed else "Баланс не найден."
        await callback.message.answer(text, reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:delete_key:"))
async def admin_delete_key(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    key = (callback.data or "").split(":", maxsplit=2)[2]
    was_removed = AccessService(config.access_users_path).delete_key(key)

    if callback.message is not None:
        text = f"Ключ <code>{key}</code> удалён." if was_removed else "Ключ не найден."
        await callback.message.answer(text, reply_markup=admin_panel_keyboard())
    await callback.answer()
