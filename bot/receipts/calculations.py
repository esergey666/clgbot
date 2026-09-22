from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import re
from zoneinfo import ZoneInfo

CENT = Decimal('0.01')


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def parse_price(value: str) -> Decimal:
    value = value.strip().replace(',', '.')
    if not re.fullmatch(r'\d{1,7}(?:\.\d{1,2})?', value):
        raise ValueError('Цена: число от 0 до 9999999,99; максимум два знака после запятой.')
    return money(Decimal(value))


def parse_quantity(value: str) -> int:
    if not re.fullmatch(r'\d{1,3}', value.strip()) or int(value) < 1:
        raise ValueError('Количество: целое число от 1 до 999.')
    return int(value)


def parse_date(value: str, timezone: str = 'Europe/Paris') -> date:
    if value.strip().lower() in ('', '-', 'сегодня'):
        return datetime.now(ZoneInfo(timezone)).date()
    if not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value.strip()):
        raise ValueError('Дата должна быть в формате ДД.ММ.ГГГГ.')
    try:
        return datetime.strptime(value.strip(), '%d.%m.%Y').date()
    except ValueError as error:
        raise ValueError('Такой даты нет. Используйте ДД.ММ.ГГГГ.') from error


def fr_money(value: Decimal) -> str:
    return f'{money(value):.2f}'.replace('.', ',')


def totals(items, rate: Decimal):
    ttc = money(sum((item.line_total for item in items), Decimal('0')))
    ht = money(ttc / (Decimal('1') + rate))
    return ttc, ht, money(ttc - ht)


def cash_payment(total: Decimal) -> tuple[Decimal, Decimal]:
    step = Decimal('50') if total <= 100 else Decimal('100')
    paid = money((total / step).to_integral_value(rounding=ROUND_CEILING) * step)
    return paid, money(paid - total)
