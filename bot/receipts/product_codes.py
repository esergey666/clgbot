"""Synthetic internal EAN-13 product codes; not registered manufacturer GTINs."""
import re
import secrets


def check_digit(first_twelve: str) -> str:
    if not re.fullmatch(r'[0-9]{12}', first_twelve):
        raise ValueError('EAN-13 requires twelve digits before the check digit.')
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first_twelve))
    return str((-total) % 10)


def validate_barcode(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{13}', value) or value[-1] != check_digit(value[:12]):
        raise ValueError('Некорректный EAN-13: нужны 13 цифр с верной контрольной цифрой.')
    return value


def generate_product_barcode() -> str:
    # Internal synthetic identifiers, independent from the article number.
    body = '20' + f'{secrets.randbelow(10**10):010d}'
    return body + check_digit(body)


def generate_numeric_code(length: int) -> str:
    """Synthetic service field; no claim about the manufacturer's encoding."""
    return f'{secrets.randbelow(10**length):0{length}d}'
