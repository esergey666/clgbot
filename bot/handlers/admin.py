from html import escape
from io import BytesIO
import logging
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import BotConfig
from bot.keyboards import (
    CLG2026_LABEL_TYPE,
    LABEL_TYPE_TITLES,
    MAIN_LABEL_TYPE,
    PRICE_TAG_LABEL_TYPE,
    RECEIPT_LABEL_TYPE,
    access_users_keyboard,
    admin_back_keyboard,
    admin_clg_keyboard,
    admin_panel_keyboard,
)
from bot.pricing import DEFAULT_GENERATION_PRICES, PRICE_LABEL_ORDER
from bot.services.access import AccessService
from bot.services.clg_pool import ClgArchiveError, ClgPair, ClgPool, read_jpg_archive
from bot.services.image_label_recognizer import ImageLabelRecognitionError, recognize_clg_source
from bot.states import AdminForm
from bot.ui import replace_ui_message, send_ui_message

router = Router()
logger = logging.getLogger(__name__)
TELEGRAM_CLOUD_DOWNLOAD_LIMIT = 20 * 1024 * 1024


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
        "⚙️ <b>Управление ботом</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"Постоянный доступ: <b>{permanent_count}</b>\n"
        f"Пользователи с балансом: <b>{balance_count}</b>\n\n"
        f"<b>Стоимость генерации</b>\n{_format_prices(config)}\n\nВыберите раздел ниже:"
    )


def _clg_panel_text(config: BotConfig) -> str:
    counts = ClgPool(config.clg_database_path, config.clg_worked_path).counts()
    return (
        "📦 <b>Закрытая база ЦЛГ</b>\n━━━━━━━━━━━━━━━━━━\n\n"
        f"Доступно: <b>{counts['available']}</b>\n"
        f"В обработке: <b>{counts['reserved']}</b>\n"
        f"Отработано: <b>{counts['used']}</b>\n"
        f"Всего в истории: <b>{counts['total']}</b>\n\n"
        "База и загрузка доступны только администраторам."
    )


def _format_user_line(access: AccessService, user_id: int, text: str) -> str:
    return f"<code>{user_id}</code> ({escape(access.format_user_label(user_id))}) — {text}"


async def _refresh_user_profiles(bot: Bot, access: AccessService, user_ids: list[int]) -> None:
    for user_id in user_ids:
        try:
            chat = await bot.get_chat(user_id)
        except Exception:
            continue

        access.record_user_profile(
            user_id,
            username=getattr(chat, "username", None),
            first_name=getattr(chat, "first_name", None),
            last_name=getattr(chat, "last_name", None),
        )


@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к админ-панели.")
        return

    await state.clear()
    await send_ui_message(message, state, _admin_panel_text(config), reply_markup=admin_panel_keyboard())


@router.callback_query(F.data == "admin:back")
async def admin_back(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message is not None:
        await replace_ui_message(callback, state, _admin_panel_text(config), reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:clg")
async def admin_clg(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    if callback.message is not None:
        await replace_ui_message(callback, state, _clg_panel_text(config), reply_markup=admin_clg_keyboard())
    await callback.answer()


@router.callback_query(F.data == "admin:clg_upload")
async def admin_clg_upload(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminForm.waiting_for_clg_sources)
    if callback.message is not None:
        await replace_ui_message(
            callback,
            state,
            "📥 <b>Загрузка ЦЛГ</b>\n\n"
            "Отправляйте фото по одному, ZIP-архив с JPG/JPEG либо текст/.txt/.csv. Каждая строка должна содержать "
            "12-значный код и ссылку.\n\n"
            "Пример: <code>783440262709, http://certilogo.com/qr/14GSH3AB5W</code>\n\n"
            "Все повторы по коду или ссылке, включая ранее отработанные, будут отсечены.",
            reply_markup=admin_clg_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "admin:clg_worked")
async def admin_clg_worked(callback: CallbackQuery, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return
    if callback.message is None:
        await callback.answer("Сообщение недоступно", show_alert=True)
        return
    path = ClgPool(config.clg_database_path, config.clg_worked_path).export_worked()
    await callback.message.answer_document(
        BufferedInputFile(path.read_bytes(), filename="отработка.csv"),
        caption="История использованных ЦЛГ.",
    )
    await callback.answer()


def _clg_import_result_text(added: int, duplicates: int, invalid: int) -> str:
    return (
        "Загрузка обработана.\n\n"
        f"Добавлено: <b>{added}</b>\n"
        f"Дубли отсечены: <b>{duplicates}</b>\n"
        f"Не распознано/ошибочных строк: <b>{invalid}</b>"
    )


@router.message(AdminForm.waiting_for_clg_sources, F.photo)
async def admin_import_clg_photo(message: Message, config: BotConfig, bot: Bot) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к базе ЦЛГ.")
        return
    buffer = BytesIO()
    await bot.download(message.photo[-1], destination=buffer)
    try:
        code, url = await recognize_clg_source(buffer.getvalue())
    except ImageLabelRecognitionError as error:
        await message.answer(f"Фото не добавлено: <code>{escape(str(error))}</code>")
        return
    result = ClgPool(config.clg_database_path, config.clg_worked_path).import_pairs([ClgPair(code, url)])
    await message.answer(_clg_import_result_text(result.added, result.duplicates, result.invalid))


@router.message(AdminForm.waiting_for_clg_sources, F.document)
async def admin_import_clg_file(message: Message, config: BotConfig, bot: Bot) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к базе ЦЛГ.")
        return
    filename = (message.document.file_name or "").lower()
    is_zip = filename.endswith(".zip")
    file_size = message.document.file_size or 0
    if is_zip and file_size > TELEGRAM_CLOUD_DOWNLOAD_LIMIT:
        await message.answer(
            "ZIP получен, но официальный Telegram Bot API не позволяет боту скачать файл больше 20 МБ.\n\n"
            "Разделите архив на части до 20 МБ каждая и отправьте их по очереди. "
            "Ограничение в 1000 фото и 500 МБ после распаковки продолжает действовать для каждого архива."
        )
        return

    download_status = await message.answer(
        "ZIP получен. Скачиваю архив…" if is_zip else "Файл получен. Скачиваю…"
    )
    buffer = BytesIO()
    try:
        await bot.download(message.document, destination=buffer)
    except Exception as error:
        logger.exception("Failed to download CLG source file %s", filename)
        await download_status.edit_text(
            "Не удалось скачать файл из Telegram. Если это ZIP, убедитесь, что его размер не превышает 20 МБ, "
            "и отправьте ещё раз.\n\n"
            f"Ошибка: <code>{escape(type(error).__name__)}</code>"
        )
        return

    if is_zip:
        try:
            images = read_jpg_archive(buffer.getvalue())
        except ClgArchiveError as error:
            await download_status.edit_text(f"Архив не обработан: <code>{escape(str(error))}</code>")
            return

        status = download_status
        await status.edit_text(f"Распознаю изображения: <b>0/{len(images)}</b>")
        pairs: list[ClgPair] = []
        failed_names: list[str] = []
        for index, (image_name, image_bytes) in enumerate(images, start=1):
            try:
                code, url = await recognize_clg_source(image_bytes)
                pairs.append(ClgPair(code, url))
            except Exception:
                logger.exception("Failed to recognize CLG source from archive member %s", image_name)
                failed_names.append(image_name)
            if index % 10 == 0 or index == len(images):
                try:
                    await status.edit_text(f"Распознаю изображения: <b>{index}/{len(images)}</b>")
                except Exception:
                    pass

        result = ClgPool(config.clg_database_path, config.clg_worked_path).import_pairs(
            pairs,
            invalid=len(failed_names),
        )
        summary = _clg_import_result_text(result.added, result.duplicates, result.invalid)
        if failed_names:
            visible = failed_names[:20]
            summary += "\n\nНе распознаны:\n" + "\n".join(f"<code>{escape(name)}</code>" for name in visible)
            if len(failed_names) > len(visible):
                summary += f"\n…и ещё {len(failed_names) - len(visible)}"
        await status.edit_text(summary)
        return

    if not filename.endswith((".txt", ".csv")):
        await download_status.edit_text("Поддерживаются файлы .txt, .csv и ZIP-архивы с JPG/JPEG.")
        return
    try:
        text = buffer.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        text = buffer.getvalue().decode("cp1251")
    result = ClgPool(config.clg_database_path, config.clg_worked_path).import_text(text)
    await download_status.edit_text(_clg_import_result_text(result.added, result.duplicates, result.invalid))


@router.message(AdminForm.waiting_for_clg_sources)
async def admin_import_clg_text(message: Message, config: BotConfig) -> None:
    if not _is_owner(message, config):
        await message.answer("У вас нет доступа к базе ЦЛГ.")
        return
    if not message.text:
        await message.answer("Отправьте фото, ZIP-архив с JPG/JPEG, текст, .txt или .csv.")
        return
    result = ClgPool(config.clg_database_path, config.clg_worked_path).import_text(message.text)
    await message.answer(_clg_import_result_text(result.added, result.duplicates, result.invalid))


@router.callback_query(F.data == "admin:grant_balance")
async def admin_grant_balance(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminForm.waiting_for_balance_grant)
    if callback.message is not None:
        await replace_ui_message(
            callback,
            state,
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
    await send_ui_message(
        message,
        state,
        "Баланс выдан.\n\n"
        f"Пользователь: <code>{user_id}</code> ({escape(access.format_user_label(user_id))})\n"
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
        await replace_ui_message(
            callback,
            state,
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
    await send_ui_message(
        message,
        state,
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
        await replace_ui_message(
            callback,
            state,
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
        await send_ui_message(
            message,
            state,
            f"Постоянный доступ выдан пользователю <code>{user_id}</code> ({escape(access.format_user_label(user_id))}).",
            reply_markup=admin_panel_keyboard(),
        )
    else:
        await send_ui_message(
            message,
            state,
            f"Пользователь <code>{user_id}</code> ({escape(access.format_user_label(user_id))}) уже был в списке.",
            reply_markup=admin_panel_keyboard(),
        )


@router.callback_query(F.data == "admin:list_users")
async def admin_list_users(callback: CallbackQuery, state: FSMContext, config: BotConfig, bot: Bot) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    access = AccessService(config.access_users_path)
    user_ids = access.list_user_ids()
    balances = access.list_balances()
    balance_user_ids = [user_id for user_id, balance in balances.items() if balance > 0]
    await _refresh_user_profiles(bot, access, sorted(set(user_ids + balance_user_ids)))

    if callback.message is not None:
        lines = [
            _format_user_line(access, user_id, "постоянный доступ")
            for user_id in user_ids
        ]
        quota_user_ids = [
            user_id
            for user_id in balance_user_ids
            if user_id not in user_ids
        ]
        lines.extend(
            _format_user_line(access, user_id, f"баланс: <b>{balance}</b>")
            for user_id, balance in balances.items()
            if balance > 0 and user_id not in user_ids
        )

        if lines:
            await replace_ui_message(
                callback,
                state,
                "Пользователи с доступом:\n" + "\n".join(lines),
                reply_markup=access_users_keyboard(user_ids, quota_user_ids),
            )
        else:
            await replace_ui_message(callback, state, "Список пользователей пуст.", reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:remove_user:"))
async def admin_remove_user(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int((callback.data or "").rsplit(":", maxsplit=1)[1])
    was_removed = AccessService(config.access_users_path).remove_user(user_id)

    if callback.message is not None:
        text = f"Постоянный доступ пользователя <code>{user_id}</code> удален." if was_removed else "Пользователь не найден."
        await replace_ui_message(callback, state, text, reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:clear_quota:"))
async def admin_clear_quota(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _is_owner_callback(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int((callback.data or "").rsplit(":", maxsplit=1)[1])
    was_removed = AccessService(config.access_users_path).clear_quota(user_id)

    if callback.message is not None:
        text = f"Баланс пользователя <code>{user_id}</code> сброшен." if was_removed else "Баланс не найден."
        await replace_ui_message(callback, state, text, reply_markup=admin_panel_keyboard())
    await callback.answer()
