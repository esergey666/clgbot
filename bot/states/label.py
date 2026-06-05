from aiogram.fsm.state import State, StatesGroup


class LabelForm(StatesGroup):
    waiting_for_label_type = State()
    waiting_for_label_data = State()
    waiting_for_access_key = State()
    waiting_for_price_article = State()
    waiting_for_price_color = State()
    waiting_for_price_size = State()
    waiting_for_price_title = State()
    waiting_for_price_old_value = State()
    waiting_for_price_value = State()
    waiting_for_receipt_data = State()
