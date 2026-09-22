import asyncio
from datetime import date
from html import escape
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import BotConfig
from bot.keyboards import RECEIPT_LABEL_TYPE, user_home_keyboard
from bot.pricing import DEFAULT_GENERATION_PRICES
from bot.services.access import AccessService
from .calculations import parse_date, parse_price, parse_quantity, fr_money
from .config import StoreConfig
from .models import Receipt, ReceiptItem
from .renderer import render
from .keyboards import cancel_keyboard, date_keyboard, items_keyboard, confirm_keyboard

router = Router()
logger = logging.getLogger(__name__)


class ReceiptForm(StatesGroup):
    date = State()
    item = State()
    more = State()
    confirm = State()


FIELDS = ('quantity', 'name_it', 'size', 'color', 'article', 'unit_price')
PROMPTS = (
    'Количество: целое число от 1 до 999.',
    'Наименование вещи <b>на итальянском</b>, до 80 символов.\nНапример: <code>GIUBBOTTO SENZA MANICHE</code>',
    'Размер, до 16 символов. Например: <code>XXL</code>',
    'Цвет, до 24 символов. Например: <code>NERO</code>. Если цвет не нужно печатать, отправьте <code>-</code>.',
    'Артикул, до 32 символов. Например: <code>8115G0123</code>',
    'Цена за одну единицу в EUR. Например: <code>395,50</code>',
)


def allowed(user_id, config):
    return AccessService(config.access_users_path).has_access(user_id, config.admin_ids)


async def begin(message, state, user_id, config):
    if not allowed(user_id, config):
        await message.answer('Для создания чека нужен активный доступ или баланс.')
        return
    await state.clear()
    await state.set_state(ReceiptForm.date)
    await state.update_data(fr_items=[])
    cost = AccessService(config.access_users_path).get_generation_prices(DEFAULT_GENERATION_PRICES)[RECEIPT_LABEL_TYPE]
    await message.answer(f'🧾 <b>Французский чек · ширина 80 мм</b>\n\n'
                         f'Наименования товаров вводятся на итальянском. До 20 позиций.\n'
                         f'PNG стоит <b>{cost}</b> с баланса за весь чек.\n\n'
                         'Введите дату покупки: <code>ДД.ММ.ГГГГ</code>.\n'
                         'Или нажмите «Сегодня» / отправьте <code>-</code>.', reply_markup=date_keyboard())


@router.message(Command('receipt_fr'))
async def command_start(message: Message, state: FSMContext, config: BotConfig):
    await begin(message, state, message.from_user.id, config)


@router.callback_query(F.data == 'fr:start')
async def callback_start(callback: CallbackQuery, state: FSMContext, config: BotConfig):
    await callback.answer()
    await begin(callback.message, state, callback.from_user.id, config)


async def next_item(message, state):
    data = await state.get_data()
    if len(data.get('fr_items', [])) >= 20:
        await message.answer('Уже добавлено 20 позиций. Нажмите «Закончить».', reply_markup=items_keyboard(20))
        return
    await state.update_data(fr_pending={}, fr_step=0)
    await state.set_state(ReceiptForm.item)
    await message.answer(f'📦 <b>Товар {len(data.get("fr_items", [])) + 1}</b>\n{PROMPTS[0]}', reply_markup=cancel_keyboard())


async def accept_date(message, state, value):
    try:
        day = parse_date(value, StoreConfig.from_env().timezone)
    except (ValueError, KeyError) as error:
        await message.answer(escape(str(error)), reply_markup=date_keyboard())
        return
    await state.update_data(fr_date=day.isoformat())
    await next_item(message, state)


@router.callback_query(ReceiptForm.date, F.data == 'fr:today')
async def today(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await accept_date(callback.message, state, '')


@router.message(ReceiptForm.date)
async def input_date(message: Message, state: FSMContext):
    await accept_date(message, state, message.text or 'invalid')


@router.message(ReceiptForm.item)
async def input_item(message: Message, state: FSMContext):
    data = await state.get_data()
    step = data['fr_step']; field = FIELDS[step]
    value = (message.text or '').strip()
    try:
        if field == 'quantity':
            value = parse_quantity(value)
        elif field == 'unit_price':
            value = str(parse_price(value))
        else:
            maximum = {'name_it': 80, 'size': 16, 'color': 24, 'article': 32}[field]
            if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError(f'Введите текст от 1 до {maximum} символов в одну строку.')
        pending = {**data['fr_pending'], field: value}
        if step == len(FIELDS) - 1:
            item = ReceiptItem.from_dict(pending)
            items = data['fr_items'] + [item.to_dict()]
            await state.update_data(fr_items=items, fr_pending={})
            await state.set_state(ReceiptForm.more)
            await message.answer(f'✅ Добавлено: {item.quantity} × {escape(item.name_it)}\n'
                                 f'Сумма: <b>{fr_money(item.line_total)} EUR</b>\n'
                                 f'Позиций в чеке: {len(items)} / 20', reply_markup=items_keyboard(len(items)))
        else:
            await state.update_data(fr_pending=pending, fr_step=step + 1)
            await message.answer(PROMPTS[step + 1], reply_markup=cancel_keyboard())
    except ValueError as error:
        await message.answer(escape(str(error)), reply_markup=cancel_keyboard())


@router.callback_query(ReceiptForm.more, F.data == 'fr:add')
async def add_item(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await next_item(callback.message, state)


def summary_pages(receipt):
    header = f'🧾 <b>Проверьте данные</b>\nДата: {receipt.purchase_date:%d.%m.%Y}\nВремя: {receipt.purchase_time:%H:%M:%S}\nКассир: {escape(receipt.display_cashier)}\n\n'
    pages, current = [], header
    for item in receipt.items:
        block = (f'{item.quantity} × {escape(item.name_it)}\n{escape(item.size)} / {escape(item.color)}\n'
                 f'ART: {escape(item.article)}\n{fr_money(item.unit_price)} EUR × {item.quantity}'
                 f' = <b>{fr_money(item.line_total)} EUR</b>\n\n')
        if len(current) + len(block) > 3000:
            pages.append(current); current = ''
        current += block
    footer = (f'Итого: <b>{fr_money(receipt.total_ttc)} EUR</b>\n'
              f'Без НДС: {fr_money(receipt.total_ht)} EUR\nTVA 20%: {fr_money(receipt.vat_amount)} EUR\n'
              f'Товаров: {receipt.article_count}\nОплата: {fr_money(receipt.cash_paid)} EUR\n'
              f'Сдача: {fr_money(receipt.change)} EUR')
    if len(current) + len(footer) > 3800:
        pages.append(current); current = ''
    pages.append(current + footer)
    return pages


@router.callback_query(ReceiptForm.more, F.data == 'fr:finish')
async def finish(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    try:
        receipt = Receipt.create(date.fromisoformat(data['fr_date']),
                                 [ReceiptItem.from_dict(item) for item in data['fr_items']], StoreConfig.from_env())
    except ValueError as error:
        await callback.message.answer(escape(str(error))); return
    await state.update_data(fr_receipt=receipt.to_dict(), fr_paid=False, fr_png_sent=False)
    await state.set_state(ReceiptForm.confirm)
    pages = summary_pages(receipt)
    for index, page in enumerate(pages):
        await callback.message.answer(page, reply_markup=confirm_keyboard() if index == len(pages) - 1 else None)


@router.callback_query(ReceiptForm.confirm, F.data == 'fr:edit')
async def edit(callback: CallbackQuery, state: FSMContext, config: BotConfig):
    data = await state.get_data()
    if data.get('fr_paid'):
        await callback.answer('Чек уже оплачен. Повторите отправку кнопкой «Создать чек».', show_alert=True); return
    await callback.answer()
    await callback.message.answer('Введите данные заново: начнём с даты.')
    await begin(callback.message, state, callback.from_user.id, config)


@router.callback_query(ReceiptForm.confirm, F.data == 'fr:create')
async def create(callback: CallbackQuery, state: FSMContext, config: BotConfig):
    await callback.answer('Готовлю файлы…')
    data = await state.get_data()
    access = AccessService(config.access_users_path)
    user_id = callback.from_user.id
    if not data.get('fr_paid') and not allowed(user_id, config):
        await callback.message.answer('Недостаточно доступа. Пополните баланс.'); return
    receipt = Receipt.from_dict(data['fr_receipt'])
    try:
        png = await asyncio.to_thread(render, receipt, StoreConfig.from_env())
    except Exception:
        logger.exception('French receipt render failed')
        await callback.message.answer('Не удалось разместить чек. Сократите длинные названия или реквизиты и повторите.', reply_markup=confirm_keyboard())
        return
    if not data.get('fr_paid'):
        cost = access.get_generation_prices(DEFAULT_GENERATION_PRICES)[RECEIPT_LABEL_TYPE]
        if not access.consume_balance(user_id, config.admin_ids, cost):
            await callback.message.answer(f'Для чека нужно {cost} с баланса. Пополните баланс и повторите.'); return
        await state.update_data(fr_paid=True)
    name = f'receipt_{receipt.purchase_date.isoformat()}_{receipt.receipt_id}'
    try:
        if not data.get('fr_png_sent'):
            await callback.message.answer_document(BufferedInputFile(png, filename=name + '.png'), caption='PNG · ширина 80 мм · 300 DPI. Длина зависит от товаров. Печать: 100%, без подгонки.')
            await state.update_data(fr_png_sent=True)
    except Exception:
        logger.exception('French receipt delivery failed')
        await callback.message.answer('Отправка прервалась. Нажмите «Создать чек» ещё раз: повторного списания не будет.', reply_markup=confirm_keyboard())
        return
    await state.clear()
    await callback.message.answer('✅ Чек готов.', reply_markup=user_home_keyboard(user_id in config.admin_ids))


@router.callback_query(F.data == 'fr:cancel')
async def cancel(callback: CallbackQuery, state: FSMContext, config: BotConfig):
    await state.clear(); await callback.answer()
    await callback.message.answer('Создание чека отменено.', reply_markup=user_home_keyboard(callback.from_user.id in config.admin_ids))


@router.callback_query(F.data.startswith('fr:'))
async def stale(callback: CallbackQuery):
    await callback.answer('Эта кнопка уже неактивна. Используйте последнее сообщение или /receipt_fr.', show_alert=True)
