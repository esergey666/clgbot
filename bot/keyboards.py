from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


MAIN_LABEL_TYPE = "main"
PRICE_TAG_LABEL_TYPE = "price_tag"
RECEIPT_LABEL_TYPE = "receipt"
CLG2026_LABEL_TYPE = "clg2026"


LABEL_TYPE_TITLES = {
    MAIN_LABEL_TYPE: "Бирка 40мм",
    CLG2026_LABEL_TYPE: "Бирка 45мм",
    PRICE_TAG_LABEL_TYPE: "Ценник",
    RECEIPT_LABEL_TYPE: "Чек",
}


def _label_with_price(label_type: str, prices: dict[str, int] | None) -> str:
    title = LABEL_TYPE_TITLES[label_type]
    if prices is None:
        return title
    return f"{title} — {prices.get(label_type, 1)}"


def label_type_keyboard(prices: dict[str, int] | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=_label_with_price(MAIN_LABEL_TYPE, prices), callback_data=f"label_type:{MAIN_LABEL_TYPE}")],
            [InlineKeyboardButton(text=_label_with_price(CLG2026_LABEL_TYPE, prices), callback_data=f"label_type:{CLG2026_LABEL_TYPE}")],
            [InlineKeyboardButton(text=_label_with_price(PRICE_TAG_LABEL_TYPE, prices), callback_data=f"label_type:{PRICE_TAG_LABEL_TYPE}")],
            [InlineKeyboardButton(text=_label_with_price(RECEIPT_LABEL_TYPE, prices), callback_data=f"label_type:{RECEIPT_LABEL_TYPE}")],
            [
                InlineKeyboardButton(text="Личный кабинет", callback_data="user:cabinet"),
                InlineKeyboardButton(text="Назад", callback_data="user:home"),
            ],
        ]
    )


def user_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать файл", callback_data="user:generate")],
            [InlineKeyboardButton(text="Личный кабинет", callback_data="user:cabinet")],
        ]
    )


def access_denied_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Личный кабинет", callback_data="user:cabinet")],
        ]
    )


def cabinet_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать файл", callback_data="user:generate")],
            [InlineKeyboardButton(text="Главное меню", callback_data="user:home")],
        ]
    )


def admin_panel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Пользователи", callback_data="admin:list_users"),
                InlineKeyboardButton(text="Выдать баланс", callback_data="admin:grant_balance"),
            ],
            [
                InlineKeyboardButton(text="Выдать постоянный доступ", callback_data="admin:add_user"),
            ],
            [
                InlineKeyboardButton(text="Цены генераций", callback_data="admin:prices"),
            ],
            [
                InlineKeyboardButton(text="Обновить панель", callback_data="admin:back"),
            ],
        ]
    )


def access_users_keyboard(user_ids: list[int], quota_user_ids: list[int] | None = None) -> InlineKeyboardMarkup:
    keyboard = []
    quota_user_ids = quota_user_ids or []

    for user_id in user_ids:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Удалить постоянный доступ: {user_id}",
                callback_data=f"admin:remove_user:{user_id}",
            )
        ])

    for user_id in quota_user_ids:
        keyboard.append([
            InlineKeyboardButton(
                text=f"Сбросить баланс: {user_id}",
                callback_data=f"admin:clear_quota:{user_id}",
            )
        ])

    keyboard.append([InlineKeyboardButton(text="Назад", callback_data="admin:back")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def admin_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Назад в админку", callback_data="admin:back")],
        ]
    )


def user_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Главное меню", callback_data="user:home")],
        ]
    )
