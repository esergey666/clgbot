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
    access_users_keyboard,
    admin_back_keyboard,
    admin_panel_keyboard,
)
from bot.pricing import DEFAULT_GENERATION_PRICES, PRICE_LABEL_ORDER
from bot.services.access import AccessService
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
        raise ValueError("Отправьте Telegram ID числом. Например: <code>123456789</code>")
    return int(value)


def _parse_balance(text: str) -> int:
    value = text.strip()
    if not value.isdigit():
        raise ValueError("Отправьте сумму баланса числом. Например: <code>100</code>")

    balance = int(value)
    if balance <= 0:
        raise ValueError("Баланс должен быть больше нуля.")
    return balance


def _parse_balance_grant(text: str) -> tuple[int, int]:
    parts = text.replace(",", " ").split()
    if len(parts) != 2:
        raise ValueError("Отправьте Telegram ID и сумму через пробел. Пример: <code>1395002445 100</code>")
    return _parse_user_id(parts[0]), _parse_balance(parts[1])


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
        raise ValueError("Отправьте цены в формате: <code>40=10, 45=15, price=5, check=20</code>")

    for part in parts:
        if "=" not in part:
            raise ValueError(f"Нет знака '=' в части: <code>{part}</code>")

        raw_key, raw_value = [item.strip() for item in part.split("=", maxsplit=1)]
        label_type = PRICE_INPUT_ALIASES.get(raw_key.lower())
        if label_type is None:
            raise ValueError(f"Неизвестный тип: <code>{raw_key}</code>")
        if not raw_value.isdigit():
            raise ValueError(f"Цена для <code>{raw_key}</code> должна быть числом.")

        price = int(raw_value)
        if price <= 0:
            raise ValueError(f"Цена для <code>{raw_key}</code> должна быть больше нуля.")
        prices[label_type] = price

    return prices


def _admin_panel_text(config: BotConfig) -> str:
    access = AccessService(config.access_users_path)
    permanent_count = len(access.list_user_ids())
    balance_count = len([balance for balance in access.list_balances().values() if balance > 0])

    return (
        "Админ-панель\n\n"
        f"Постоянный доступ: <b>{permanent_count}</b>\n"
        f"Пользователи с балансом: <b>{balance_count}</b>\n\n"
        "Выберите действие:"
    )


def _format_user_line(access: AccessService, user_id: int, text: str) -> str:
    return f"<code>{user_id}</code> ({access.format_user_label(user_id)}) — {text}"


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


@router.callback_query(F.data == "admin:grant_balance")
async def admin_grant_balance(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_for_balance_grant)
    if callback.message is not None:
        await callback.message.answer(
            "Выдать баланс пользователю\n\n"
            "Отправьте Telegram ID и сумму через пробел:\n"
            "<code>1395002445 100</code>",
            reply_markup=admin_back_keyboard(),
        )
    await callback.answer()


@router.message(AdminForm.waiting_for_balance_grant)
async def admin_save_balance_grant(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return
    if message.text is None:
        await message.answer("Отправьте Telegram ID и сумму текстом. Пример: <code>1395002445 100</code>")
        return

    try:
        user_id, amount = _parse_balance_grant(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    access = AccessService(config.access_users_path)
    new_balance = access.add_balance(user_id, amount)
    await state.clear()
    await message.answer(
        "Баланс выдан.\n\n"
        f"Пользователь: <code>{user_id}</code> ({access.format_user_label(user_id)})\n"
        f"Начислено: <b>{amount}</b>\n"
        f"Текущий баланс: <b>{new_balance}</b>",
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
        await message.answer(
            f"Постоянный доступ выдан пользователю <code>{user_id}</code> ({access.format_user_label(user_id)}).",
            reply_markup=admin_panel_keyboard(),
        )
    else:
        await message.answer(
            f"Пользователь <code>{user_id}</code> ({access.format_user_label(user_id)}) уже был в списке.",
            reply_markup=admin_panel_keyboard(),
        )


@router.callback_query(F.data == "admin:list_users")
async def admin_list_users(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    access = AccessService(config.access_users_path)
    user_ids = access.list_user_ids()
    balances = access.list_balances()

    if callback.message is not None:
        lines = [
            _format_user_line(access, user_id, "постоянный доступ")
            for user_id in user_ids
        ]
        quota_user_ids = [
            user_id
            for user_id, balance in balances.items()
            if balance > 0 and user_id not in user_ids
        ]
        lines.extend(
            _format_user_line(access, user_id, f"баланс: <b>{balance}</b>")
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


@router.callback_query(F.data.startswith("admin:remove_user:"))
async def admin_remove_user(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int((callback.data or "").rsplit(":", maxsplit=1)[1])
    was_removed = AccessService(config.access_users_path).remove_user(user_id)

    if callback.message is not None:
        text = f"Постоянный доступ пользователя <code>{user_id}</code> удален." if was_removed else "Пользователь не найден."
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
