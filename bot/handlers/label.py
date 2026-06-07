from io import BytesIO
import logging
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import BotConfig
from bot.keyboards import (
    CLG2026_LABEL_TYPE,
    LABEL_TYPE_TITLES,
    MAIN_LABEL_TYPE,
    PRICE_TAG_LABEL_TYPE,
    RECEIPT_LABEL_TYPE,
    access_denied_keyboard,
    label_prices_text,
    label_type_keyboard,
    user_home_keyboard,
)
from bot.pricing import DEFAULT_GENERATION_PRICES
from bot.services.access import AccessService
from bot.services.price_tag_renderer import PriceTagData, PriceTagRenderer, normalize_model_code
from bot.services.receipt_renderer import ReceiptData, ReceiptRenderer
from bot.states import LabelForm
from bot.ui import replace_ui_message, send_ui_message

router = Router()
logger = logging.getLogger(__name__)


def _message_has_access(message: Message, config: BotConfig) -> bool:
    if message.from_user is not None:
        AccessService(config.access_users_path).record_user_profile(
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
        )
    return message.from_user is not None and AccessService(config.access_users_path).has_access(
        message.from_user.id,
        config.admin_ids,
    )


def _callback_has_access(callback: CallbackQuery, config: BotConfig) -> bool:
    AccessService(config.access_users_path).record_user_profile(
        callback.from_user.id,
        username=callback.from_user.username,
        first_name=callback.from_user.first_name,
        last_name=callback.from_user.last_name,
    )
    return AccessService(config.access_users_path).has_access(
        callback.from_user.id,
        config.admin_ids,
    )


def _get_generation_price(config: BotConfig, label_type: str) -> int:
    return AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES).get(label_type, 1)


def _label_type_keyboard(config: BotConfig):
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    return label_type_keyboard(prices)


def _generation_prices_text(config: BotConfig) -> str:
    prices = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)
    return label_prices_text(prices)


def _get_generation_cost(config: BotConfig, label_type: str, count: int = 1) -> int:
    return _get_generation_price(config, label_type) * count


async def _try_consume_balance(message: Message, config: BotConfig, amount: int) -> bool:
    if message.from_user is None:
        await message.answer("Не удалось определить пользователя.")
        return False

    access = AccessService(config.access_users_path)
    if access.consume_balance(message.from_user.id, config.admin_ids, amount):
        return True

    remaining = access.get_balance(message.from_user.id)
    await message.answer(
        f"Недостаточно баланса. Нужно: <b>{amount}</b>, осталось: <b>{remaining}</b>.\n"
        "Отправьте новый ключ доступа.",
        reply_markup=access_denied_keyboard(),
    )
    return False


async def _send_remaining_balance(message: Message, config: BotConfig) -> None:
    if message.from_user is None:
        return

    access = AccessService(config.access_users_path)
    if message.from_user.id in config.admin_ids or message.from_user.id in access.list_user_ids():
        return

    remaining = access.get_balance(message.from_user.id)
    await message.answer(f"Баланс: <b>{remaining}</b>")


MAIN_FORMAT = "артикул, цвет, размер, код, certilogo_code, certilogo_url"
PRICE_TAG_FORMAT = "артикул, цвет, размер, название, старая цена, цена со скидкой"
RECEIPT_FORMAT = "артикул, цвет, размер, название, цена[, дата/время]"
LABEL_TYPE_FILE_SLUGS = {
    MAIN_LABEL_TYPE: "birka_40mm",
    CLG2026_LABEL_TYPE: "birka_45mm",
    PRICE_TAG_LABEL_TYPE: "cennik",
    RECEIPT_LABEL_TYPE: "check",
}


def _parse_label_line(line: str, expected_parts: int) -> list[str]:
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != expected_parts or any(not part for part in parts):
        raise ValueError
    return parts


def _parse_label_list(text: str, expected_parts: int) -> list[list[str]]:
    labels: list[list[str]] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            labels.append(_parse_label_line(line, expected_parts))
        except ValueError as error:
            raise ValueError(f"строка {line_number}: {line}") from error

    if not labels:
        raise ValueError("список пуст")

    return labels


def _format_certilogo_code(certilogo_code: str) -> str:
    compact_code = certilogo_code.replace(" ", "")
    return "  ".join([compact_code[i:i + 3] for i in range(0, len(compact_code), 3)])


def _format_clg_code(certilogo_code: str) -> str:
    compact_code = certilogo_code.replace(" ", "")
    return "  ".join([compact_code[i:i + 3] for i in range(0, len(compact_code), 3)])


def _get_label_type_name(label_type: str) -> str:
    return LABEL_TYPE_TITLES.get(label_type, LABEL_TYPE_TITLES[MAIN_LABEL_TYPE])


def _get_label_file_slug(label_type: str) -> str:
    return LABEL_TYPE_FILE_SLUGS.get(label_type, LABEL_TYPE_FILE_SLUGS[MAIN_LABEL_TYPE])


def _get_label_format(label_type: str) -> str:
    if label_type == PRICE_TAG_LABEL_TYPE:
        return PRICE_TAG_FORMAT
    if label_type == RECEIPT_LABEL_TYPE:
        return RECEIPT_FORMAT
    return MAIN_FORMAT


def _get_expected_parts(label_type: str) -> int:
    return 6


def _get_required_asset_paths(label_type: str, config: BotConfig) -> list[Path]:
    if label_type == RECEIPT_LABEL_TYPE:
        return [
            config.receipt_template_path,
            config.font_path,
        ]
    if label_type == PRICE_TAG_LABEL_TYPE:
        return [
            config.price_tag_template_path,
            config.font_path,
        ]
    if label_type == CLG2026_LABEL_TYPE:
        return [
            config.clg2026_template_path,
            config.clg2026_arial_font_path,
            config.clg2026_arial_bold_font_path,
            config.number_font_path,
            config.qr_template_path,
        ]

    return [
        config.template_path,
        config.font_path,
        config.number_font_path,
        config.qr_template_path,
    ]


def _get_missing_asset_paths(label_type: str, config: BotConfig) -> list[Path]:
    return [path for path in _get_required_asset_paths(label_type, config) if not path.exists()]


async def _get_selected_label_type(state: FSMContext) -> str | None:
    data = await state.get_data()
    label_type = data.get("label_type")
    if label_type in {MAIN_LABEL_TYPE, PRICE_TAG_LABEL_TYPE, CLG2026_LABEL_TYPE, RECEIPT_LABEL_TYPE}:
        return label_type
    return None


def _normalize_price_article(value: str) -> str:
    try:
        return normalize_model_code(value)
    except ValueError as error:
        raise ValueError("Артикул должен быть из 9 цифр или латинских букв. Можно отправить 801564651, 80152RC87 или MO801564651.") from error


def _normalize_price_color(value: str) -> str:
    color = value.strip().upper().replace(" ", "")
    if not color:
        raise ValueError("Цвет не должен быть пустым. Пример: A0029.")
    return color


def _normalize_price_size(value: str) -> str:
    size = value.strip().upper()
    if not size:
        raise ValueError("Размер не должен быть пустым. Пример: XL.")
    return size


def _normalize_price_title(value: str) -> str:
    title = " ".join(value.strip().split())
    if not title:
        raise ValueError("Наименование не должно быть пустым. Пример: shorts jogger.")
    return title


def _normalize_price_value(value: str) -> str:
    price = value.strip().replace(" ", "").replace(",", ".")
    try:
        number = float(price)
    except ValueError as error:
        raise ValueError("Цена должна быть числом. Пример: 250.") from error
    if number <= 0:
        raise ValueError("Цена должна быть больше нуля.")
    return price


async def _send_price_tag(message: Message, state: FSMContext, config: BotConfig) -> bool:
    missing_paths = _get_missing_asset_paths(PRICE_TAG_LABEL_TYPE, config)
    if missing_paths:
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False
    if not await _try_consume_balance(message, config, _get_generation_cost(config, PRICE_TAG_LABEL_TYPE)):
        return False

    data = await state.get_data()
    renderer = PriceTagRenderer(config.price_tag_template_path, config.font_path)
    image = renderer.render(
        PriceTagData(
            model_code=data["price_article"],
            color_code=data["price_color"],
            size=data["price_size"],
            title=data["price_title"],
            price=data["price_value"],
            old_price=data["price_old_value"],
        )
    )

    await message.answer_document(
        document=BufferedInputFile(image.getvalue(), filename="cennik.png"),
        caption="Готово.",
    )
    await _send_remaining_balance(message, config)
    return True


def _normalize_price_tag_parts(parts: list[str]) -> PriceTagData:
    return PriceTagData(
        model_code=_normalize_price_article(parts[0]),
        color_code=_normalize_price_color(parts[1]),
        size=_normalize_price_size(parts[2]),
        title=_normalize_price_title(parts[3]),
        old_price=_normalize_price_value(parts[4]),
        price=_normalize_price_value(parts[5]),
    )


def _normalize_receipt_parts(parts: list[str]) -> ReceiptData:
    if len(parts) not in {5, 6}:
        raise ValueError("Для чека нужно 5 полей без даты или 6 полей с датой.")
    price = _normalize_price_value(parts[4])
    date_time = parts[5].strip() if len(parts) == 6 else None
    return ReceiptData(
        article=_normalize_price_article(parts[0])[2:],
        color=parts[1].strip().upper(),
        size=parts[2].strip().upper(),
        item_name=parts[3].strip(),
        price=price,
        **({"date_time": date_time} if date_time else {}),
    )


def _parse_receipt_list(text: str) -> list[list[str]]:
    receipts: list[list[str]] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        parts = [part.strip() for part in line.split(",")]
        if len(parts) not in {5, 6} or any(not part for part in parts):
            raise ValueError(f"строка {line_number}: {line}")
        receipts.append(parts)

    if not receipts:
        raise ValueError("список пуст")

    return receipts


async def _send_receipt(message: Message, parts: list[str], config: BotConfig) -> bool:
    missing_paths = _get_missing_asset_paths(RECEIPT_LABEL_TYPE, config)
    if missing_paths:
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False

    try:
        data = _normalize_receipt_parts(parts)
    except ValueError as error:
        await message.answer(str(error))
        return False

    if not await _try_consume_balance(message, config, _get_generation_cost(config, RECEIPT_LABEL_TYPE)):
        return False

    renderer = ReceiptRenderer(config.receipt_template_path, config.font_path)
    image = renderer.render(data)
    await message.answer_document(
        document=BufferedInputFile(image.getvalue(), filename="check.png"),
        caption="Готово.",
    )
    await _send_remaining_balance(message, config)
    return True


async def _send_many_receipts(message: Message, receipts: list[list[str]], config: BotConfig) -> bool:
    missing_paths = _get_missing_asset_paths(RECEIPT_LABEL_TYPE, config)
    if missing_paths:
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False

    items: list[ReceiptData] = []
    for index, parts in enumerate(receipts, start=1):
        try:
            items.append(_normalize_receipt_parts(parts))
        except ValueError as error:
            await message.answer(f"Ошибка в строке {index}: <code>{error}</code>")
            return False

    if not await _try_consume_balance(message, config, _get_generation_cost(config, RECEIPT_LABEL_TYPE, len(items))):
        return False

    status_message = await message.answer(
        f"Принял список: {len(items)} шт. Генерирую чеки..."
    )
    archive_buffer = BytesIO()
    renderer = ReceiptRenderer(config.receipt_template_path, config.font_path)

    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index, item in enumerate(items, start=1):
            image = renderer.render(item)
            filename = f"check_{index:03d}_{item.article}_{item.color}_{item.size}.png"
            archive.writestr(filename, image.getvalue())

    archive_buffer.seek(0)

    await message.answer_document(
        document=BufferedInputFile(archive_buffer.getvalue(), filename="checks.zip"),
        caption=f"Готово! Сгенерировано чеков: {len(items)}",
    )
    await status_message.delete()
    await _send_remaining_balance(message, config)
    return True


async def _send_receipt_list_from_text(message: Message, text: str, config: BotConfig) -> bool:
    receipts = _parse_receipt_list(text)
    return await _send_many_receipts(message, receipts, config)


async def _send_many_price_tags(message: Message, labels: list[list[str]], config: BotConfig) -> bool:
    missing_paths = _get_missing_asset_paths(PRICE_TAG_LABEL_TYPE, config)
    if missing_paths:
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False
    items: list[PriceTagData] = []
    for index, parts in enumerate(labels, start=1):
        try:
            items.append(_normalize_price_tag_parts(parts))
        except ValueError as error:
            await message.answer(f"Ошибка в строке {index}: <code>{error}</code>")
            return False

    if not await _try_consume_balance(message, config, _get_generation_cost(config, PRICE_TAG_LABEL_TYPE, len(items))):
        return False

    status_message = await message.answer(
        f"Принял список: {len(items)} шт. Генерирую ценники..."
    )
    archive_buffer = BytesIO()
    renderer = PriceTagRenderer(config.price_tag_template_path, config.font_path)

    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index, item in enumerate(items, start=1):
            image = renderer.render(item)
            filename = f"cennik_{index:03d}_{item.model_code}_{item.color_code}_{item.size}.png"
            archive.writestr(filename, image.getvalue())

    archive_buffer.seek(0)

    await message.answer_document(
        document=BufferedInputFile(archive_buffer.getvalue(), filename="cenniki.zip"),
        caption=f"Готово! Сгенерировано ценников: {len(items)}",
    )
    await status_message.delete()
    await _send_remaining_balance(message, config)
    return True


async def _send_price_tag_list_from_text(message: Message, text: str, config: BotConfig) -> bool:
    labels = _parse_label_list(text, _get_expected_parts(PRICE_TAG_LABEL_TYPE))
    return await _send_many_price_tags(message, labels, config)


async def _generate_main_label_image(parts: list[str], config: BotConfig) -> BytesIO:
    from bot.services.label_generator import LabelGenerator

    label = LabelGenerator(
        config.template_path,
        config.font_path,
        config.number_font_path,
        config.qr_template_path,
    )

    return await label.generate_label(
        art=parts[0],
        color=parts[1],
        size_tag=parts[2],
        code=parts[3],
        certilogo_code=_format_clg_code(parts[4]),
        certilogo_url=parts[5],
    )


async def _generate_clg2026_label_image(parts: list[str], config: BotConfig) -> BytesIO:
    from bot.services.clg2026_generator import Clg2026Generator

    label = Clg2026Generator(
        config.clg2026_template_path,
        config.clg2026_arial_font_path,
        config.clg2026_arial_bold_font_path,
        config.number_font_path,
        config.qr_template_path,
    )

    return await label.generate_label(
        art=parts[0],
        color=parts[1],
        size_tag=parts[2],
        code=parts[3],
        certilogo_code=_format_certilogo_code(parts[4]),
        certilogo_url=parts[5],
    )


async def _generate_label_image(parts: list[str], label_type: str, config: BotConfig) -> BytesIO:
    if label_type == CLG2026_LABEL_TYPE:
        return await _generate_clg2026_label_image(parts, config)
    return await _generate_main_label_image(parts, config)


async def _send_single_label(message: Message, parts: list[str], label_type: str, config: BotConfig) -> bool:
    logger.info("Single label request started: type=%s parts=%s", label_type, parts)
    missing_paths = _get_missing_asset_paths(label_type, config)
    if missing_paths:
        logger.warning("Missing assets for %s: %s", label_type, missing_paths)
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False
    if not await _try_consume_balance(message, config, _get_generation_cost(config, label_type)):
        logger.info("Single label request stopped by balance check: type=%s", label_type)
        return False

    status_message = await message.answer("Начинаю генерацию...")

    try:
        logger.info("Generating image: type=%s", label_type)
        image = await _generate_label_image(parts, label_type, config)
        logger.info("Image generated: type=%s bytes=%s", label_type, len(image.getvalue()))
    except Exception as error:
        logger.exception("Failed to generate %s label", label_type)
        await message.answer(
            "Не удалось сгенерировать файл на хостинге.\n\n"
            f"Ошибка: <code>{type(error).__name__}: {error}</code>\n\n"
            "Если это бирка 40/45 мм, проверьте, что на хостинге установлена системная библиотека <code>libdmtx0b</code>."
        )
        return False

    logger.info("Sending generated document: type=%s", label_type)
    await message.answer_document(
        document=BufferedInputFile(image.getvalue(), filename=f"{_get_label_file_slug(label_type)}.png")
    )
    logger.info("Generated document sent: type=%s", label_type)
    await status_message.delete()
    await _send_remaining_balance(message, config)
    return True


async def _send_many_labels(message: Message, labels: list[list[str]], label_type: str, config: BotConfig) -> bool:
    missing_paths = _get_missing_asset_paths(label_type, config)
    if missing_paths:
        await message.answer(
            "Не хватает файлов шаблона:\n"
            + "\n".join(f"<code>{path}</code>" for path in missing_paths)
        )
        return False
    if not await _try_consume_balance(message, config, _get_generation_cost(config, label_type, len(labels))):
        return False

    status_message = await message.answer(
        f"Принял список: {len(labels)} шт. Генерирую бирки..."
    )

    archive_buffer = BytesIO()

    with ZipFile(archive_buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index, parts in enumerate(labels, start=1):
            try:
                image = await _generate_label_image(parts, label_type, config)
            except Exception as error:
                logger.exception("Failed to generate %s label from line %s", label_type, index)
                await message.answer(
                    f"Не удалось сгенерировать файл из строки {index}.\n\n"
                    f"Ошибка: <code>{type(error).__name__}: {error}</code>\n\n"
                    "Если это бирка 40/45 мм, проверьте, что на хостинге установлена системная библиотека <code>libdmtx0b</code>."
                )
                return False
            filename = f"{_get_label_file_slug(label_type)}_{index:03d}_{parts[0]}_{parts[1]}_{parts[2]}.png"
            archive.writestr(filename, image.getvalue())

    archive_buffer.seek(0)

    await message.answer_document(
        document=BufferedInputFile(archive_buffer.getvalue(), filename=f"{_get_label_file_slug(label_type)}.zip"),
        caption=f"Готово! Сгенерировано бирок: {len(labels)}",
    )
    await status_message.delete()
    await _send_remaining_balance(message, config)
    return True


@router.callback_query(LabelForm.waiting_for_label_type, F.data.startswith("label_type:"))
async def handle_label_type(callback: CallbackQuery, state: FSMContext, config: BotConfig) -> None:
    if not _callback_has_access(callback, config):
        await callback.answer("Нет доступа", show_alert=True)
        return

    label_type = (callback.data or "").split(":", maxsplit=1)[1]
    if label_type not in {MAIN_LABEL_TYPE, PRICE_TAG_LABEL_TYPE, CLG2026_LABEL_TYPE, RECEIPT_LABEL_TYPE}:
        await callback.answer("Неизвестный тип бирки", show_alert=True)
        return

    await state.update_data(label_type=label_type)

    if label_type == RECEIPT_LABEL_TYPE:
        await state.set_state(LabelForm.waiting_for_receipt_data)
        if callback.message is not None:
            await replace_ui_message(
                callback,
                state,
                f"Выбрано: {_get_label_type_name(label_type)}\n\n"
                "Отправьте данные одной строкой:\n"
                f"<code>{RECEIPT_FORMAT}</code>\n\n"
                "Пример:\n"
                "<code>801564651, A0029, XL, SHORTS, 110</code>\n\n"
                "Со своей датой:\n"
                "<code>801564651, A0029, XL, SHORTS, 110, 30/04/2026 05:54 PM</code>\n\n"
                "Для массовой генерации отправьте .txt, где каждая строка в таком формате."
            )
        await callback.answer()
        return

    if label_type == PRICE_TAG_LABEL_TYPE:
        await state.set_state(LabelForm.waiting_for_price_article)
        if callback.message is not None:
            await replace_ui_message(
                callback,
                state,
                f"Выбрано: {_get_label_type_name(label_type)}\n\n"
                "Введите артикул: 9 цифр без MO. Пример: <code>801564651</code>\n\n"
                "Для массовой генерации отправьте .txt или несколько строк текстом:\n"
                f"<code>{PRICE_TAG_FORMAT}</code>"
            )
        await callback.answer()
        return

    await state.set_state(LabelForm.waiting_for_label_data)

    label_name = _get_label_type_name(label_type)
    label_format = _get_label_format(label_type)
    text = (
        f"Выбрано: {label_name}\n\n"
        "Отправьте данные одной строкой в формате:\n"
        f"<code>{label_format}</code>\n\n"
        "Для массовой генерации можно отправить .txt, где каждая строка в таком же формате."
    )

    if callback.message is not None:
        await replace_ui_message(callback, state, text)
    await callback.answer()


@router.message(LabelForm.waiting_for_label_type)
async def handle_missing_label_type(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return

    await send_ui_message(
        message,
        state,
        "Сначала выберите, что сделать:\n\n"
        "Стоимость генерации:\n"
        f"{_generation_prices_text(config)}",
        reply_markup=_label_type_keyboard(config),
    )


@router.message(LabelForm.waiting_for_price_article, F.document)
async def handle_price_tag_file(message: Message, state: FSMContext, config: BotConfig, bot: Bot) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return

    document = message.document
    if document is None:
        await message.answer("Не удалось прочитать документ.")
        return

    filename = document.file_name or ""
    if not filename.lower().endswith(".txt"):
        await message.answer("Отправьте список именно в .txt файле.")
        return

    file_buffer = BytesIO()
    await bot.download(document, destination=file_buffer)

    try:
        text = file_buffer.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_buffer.getvalue().decode("cp1251")

    try:
        was_sent = await _send_price_tag_list_from_text(message, text, config)
    except ValueError as error:
        await message.answer(
            "В списке есть ошибка. Формат каждой строки должен быть такой:\n"
            f"<code>{PRICE_TAG_FORMAT}</code>\n\n"
            f"Проблема: <code>{error}</code>"
        )
        return

    if was_sent:
        await state.set_state(LabelForm.waiting_for_label_type)
        await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())


@router.message(LabelForm.waiting_for_receipt_data, F.document)
async def handle_receipt_file(message: Message, state: FSMContext, config: BotConfig, bot: Bot) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return

    document = message.document
    if document is None:
        await message.answer("Не удалось прочитать документ.")
        return

    filename = document.file_name or ""
    if not filename.lower().endswith(".txt"):
        await message.answer("Отправьте список именно в .txt файле.")
        return

    file_buffer = BytesIO()
    await bot.download(document, destination=file_buffer)

    try:
        text = file_buffer.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_buffer.getvalue().decode("cp1251")

    try:
        was_sent = await _send_receipt_list_from_text(message, text, config)
    except ValueError as error:
        await message.answer(
            "В списке есть ошибка. Формат каждой строки должен быть такой:\n"
            f"<code>{RECEIPT_FORMAT}</code>\n\n"
            f"Проблема: <code>{error}</code>"
        )
        return

    if was_sent:
        await state.set_state(LabelForm.waiting_for_label_type)
        await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())


@router.message(LabelForm.waiting_for_receipt_data)
async def handle_receipt_data(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer(
            "Отправьте данные текстом:\n"
            f"<code>{RECEIPT_FORMAT}</code>"
        )
        return

    if "\n" in message.text.strip():
        try:
            was_sent = await _send_receipt_list_from_text(message, message.text, config)
        except ValueError as error:
            await message.answer(
                "Неверный формат. Для массовой генерации используйте строки:\n"
                f"<code>{RECEIPT_FORMAT}</code>\n\n"
                f"Проблема: <code>{error}</code>"
            )
            return

        if was_sent:
            await state.set_state(LabelForm.waiting_for_label_type)
            await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())
        return

    parts = [part.strip() for part in message.text.strip().split(",")]
    if len(parts) not in {5, 6} or any(not part for part in parts):
        await message.answer(
            "Неверный формат. Отправьте строку так:\n"
            f"<code>{RECEIPT_FORMAT}</code>\n\n"
            "Пример:\n"
            "<code>801564651, A0029, XL, SHORTS, 110</code>\n\n"
            "Со своей датой:\n"
            "<code>801564651, A0029, XL, SHORTS, 110, 30/04/2026 05:54 PM</code>"
        )
        return

    was_sent = await _send_receipt(message, parts, config)
    if not was_sent:
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())


@router.message(LabelForm.waiting_for_price_article)
async def handle_price_article(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer("Введите артикул текстом: 9 цифр. Пример: <code>801564651</code>")
        return

    if "," in message.text or "\n" in message.text:
        try:
            was_sent = await _send_price_tag_list_from_text(message, message.text, config)
        except ValueError as error:
            await message.answer(
                "Неверный формат. Для массовой генерации используйте строки:\n"
                f"<code>{PRICE_TAG_FORMAT}</code>\n\n"
                f"Проблема: <code>{error}</code>"
            )
            return

        if was_sent:
            await state.set_state(LabelForm.waiting_for_label_type)
            await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())
        return

    try:
        article = _normalize_price_article(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_article=article)
    await state.set_state(LabelForm.waiting_for_price_color)
    await send_ui_message(message, state, "Введите цвет. Пример: <code>A0029</code>")


@router.message(LabelForm.waiting_for_price_color)
async def handle_price_color(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer("Введите цвет текстом. Пример: <code>A0029</code>")
        return

    try:
        color = _normalize_price_color(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_color=color)
    await state.set_state(LabelForm.waiting_for_price_size)
    await send_ui_message(message, state, "Введите размер. Пример: <code>XL</code>")


@router.message(LabelForm.waiting_for_price_size)
async def handle_price_size(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer("Введите размер текстом. Пример: <code>XL</code>")
        return

    try:
        size = _normalize_price_size(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_size=size)
    await state.set_state(LabelForm.waiting_for_price_title)
    await send_ui_message(message, state, "Введите наименование вещи. Пример: <code>shorts jogger</code>")


@router.message(LabelForm.waiting_for_price_title)
async def handle_price_title(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer("Введите наименование текстом. Пример: <code>shorts jogger</code>")
        return

    try:
        title = _normalize_price_title(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_title=title)
    await state.set_state(LabelForm.waiting_for_price_old_value)
    await send_ui_message(message, state, "Введите старую цену без скидки. Пример: <code>500</code>")


@router.message(LabelForm.waiting_for_price_old_value)
async def handle_price_old_value(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("РЈ РІР°СЃ РЅРµС‚ РґРѕСЃС‚СѓРїР° Рє РёСЃРїРѕР»СЊР·РѕРІР°РЅРёСЋ СЌС‚РѕРіРѕ Р±РѕС‚Р°.")
        return
    if message.text is None:
        await message.answer("Введите старую цену числом. Пример: <code>500</code>")
        return

    try:
        old_price = _normalize_price_value(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_old_value=old_price)
    await state.set_state(LabelForm.waiting_for_price_value)
    await send_ui_message(message, state, "Введите цену со скидкой. Пример: <code>250</code>")


@router.message(LabelForm.waiting_for_price_value)
async def handle_price_value(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return
    if message.text is None:
        await message.answer("Введите цену со скидкой числом. Пример: <code>250</code>")
        return

    try:
        price = _normalize_price_value(message.text)
    except ValueError as error:
        await message.answer(str(error))
        return

    await state.update_data(price_value=price)
    was_sent = await _send_price_tag(message, state, config)
    if not was_sent:
        return
    await state.set_state(LabelForm.waiting_for_label_type)
    await send_ui_message(message, state, "Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())


@router.message(LabelForm.waiting_for_label_data, F.document)
async def handle_label_file(message: Message, state: FSMContext, config: BotConfig, bot: Bot) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return

    label_type = await _get_selected_label_type(state)
    if label_type is None:
        await send_ui_message(
            message,
            state,
            "Сначала выберите, что сделать:\n\n"
            "Стоимость генерации:\n"
            f"{_generation_prices_text(config)}",
            reply_markup=_label_type_keyboard(config),
        )
        await state.set_state(LabelForm.waiting_for_label_type)
        return

    document = message.document
    if document is None:
        await message.answer("Не удалось прочитать документ.")
        return

    filename = document.file_name or ""
    if not filename.lower().endswith(".txt"):
        await message.answer("Отправьте список именно в .txt файле.")
        return

    file_buffer = BytesIO()
    await bot.download(document, destination=file_buffer)

    try:
        text = file_buffer.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        text = file_buffer.getvalue().decode("cp1251")

    try:
        labels = _parse_label_list(text, _get_expected_parts(label_type))
        was_sent = await _send_many_labels(message, labels, label_type, config)
        if was_sent:
            await state.set_state(LabelForm.waiting_for_label_type)
            await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())
    except ValueError as error:
        await message.answer(
            "В списке есть ошибка. Формат каждой строки должен быть такой:\n"
            f"<code>{_get_label_format(label_type)}</code>\n\n"
            f"Проблема: <code>{error}</code>"
        )


@router.message(LabelForm.waiting_for_label_data)
async def handle_label_data(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.")
        return

    label_type = await _get_selected_label_type(state)
    if label_type is None:
        await send_ui_message(
            message,
            state,
            "Сначала выберите, что сделать:\n\n"
            "Стоимость генерации:\n"
            f"{_generation_prices_text(config)}",
            reply_markup=_label_type_keyboard(config),
        )
        await state.set_state(LabelForm.waiting_for_label_type)
        return

    if message.text is None:
        await message.answer(
            "Сообщение не содержит текст. Отправьте данные текстом или .txt файлом."
        )
        return

    try:
        labels = _parse_label_list(message.text.strip(), _get_expected_parts(label_type))

        if len(labels) == 1:
            was_sent = await _send_single_label(message, labels[0], label_type, config)
        else:
            was_sent = await _send_many_labels(message, labels, label_type, config)

        if was_sent:
            await state.set_state(LabelForm.waiting_for_label_type)
            await message.answer("Готово. Можно создать следующий файл:", reply_markup=user_home_keyboard())

    except ValueError:
        await message.answer(
            "Неверный формат. Попробуйте еще раз:\n"
            f"<code>{_get_label_format(label_type)}</code>\n\n"
            "Для массовой генерации можно отправить несколько строк текстом или .txt файлом."
        )

@router.message()
async def handle_unexpected_message(message: Message, state: FSMContext, config: BotConfig) -> None:
    if not _message_has_access(message, config):
        await message.answer("У вас нет доступа к использованию этого бота.", reply_markup=access_denied_keyboard())
        return

    await state.set_state(LabelForm.waiting_for_label_type)
    await message.answer(
        "Я получил сообщение, но сейчас не выбран тип файла.\n\n"
        "Нажмите «Создать файл» и выберите, что нужно сгенерировать.",
        reply_markup=user_home_keyboard(),
    )
