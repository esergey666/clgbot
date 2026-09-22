from datetime import datetime, time
import base64
import secrets
from uuid import uuid4


def purchase_time(opens: str, closes: str) -> time:
    try:
        start = datetime.strptime(opens, '%H:%M').time()
        end = datetime.strptime(closes, '%H:%M').time()
    except ValueError as error:
        raise ValueError('Часы магазина должны быть в формате ЧЧ:ММ.') from error
    first = start.hour * 3600 + start.minute * 60
    last = end.hour * 3600 + end.minute * 60
    if first >= last:
        raise ValueError('Закрытие магазина должно быть позже открытия.')
    seconds = first + secrets.randbelow(last - first + 1)
    return time(seconds // 3600, seconds % 3600 // 60, seconds % 60)


def identifiers(day, consultants):
    uid = uuid4()
    receipt_id = f'RCPT-{day:%Y%m%d}-{uid.hex[:16].upper()}'
    establishment = f'S{secrets.randbelow(999):03d}'
    cashier = secrets.choice(consultants)
    return dict(receipt_id=receipt_id, document_id=str(uid),
                receipt_number=f'{day:%y}{uid.int % 10**6:06d}',
                establishment_id=establishment,
                register_id=f'{establishment}C{secrets.randbelow(9) + 1}',
                sale_id=uuid4().hex.upper(), seller_number=f'{secrets.randbelow(90000) + 10000}',
                consultant_name=cashier, cashier_name=cashier,
                barcode_value=f'01B{secrets.randbelow(10**10):010d}',
                # Synthetic 96-character service code, not a fiscal signature.
                control_code=base64.b64encode(secrets.token_bytes(72)).decode('ascii'))
