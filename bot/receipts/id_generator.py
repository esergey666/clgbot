from datetime import datetime, time
import hashlib
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
    return dict(receipt_id=receipt_id, document_id=str(uid),
                receipt_number=f'{day:%y%m%d}{uid.int % 10**10:010d}',
                establishment_id=establishment,
                register_id=f'{establishment}C{secrets.randbelow(9) + 1}',
                sale_id=uuid4().hex.upper(), seller_number=f'{secrets.randbelow(90000) + 10000}',
                consultant_name=secrets.choice(consultants),
                control_code=hashlib.sha256(str(uid).encode()).hexdigest()[:24].upper())
