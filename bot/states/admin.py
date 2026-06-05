from aiogram.fsm.state import State, StatesGroup


class AdminForm(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_key_generations = State()
    waiting_for_generation_prices = State()
