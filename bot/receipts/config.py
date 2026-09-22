from dataclasses import dataclass
from decimal import Decimal
from os import getenv
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class StoreConfig:
    name: str = 'STONE ISLAND'
    address_1: str = '3 Cours de la Garonne'
    address_2: str = '77700 Serris'
    phone: str = 'TEL: +33 1 73095050'
    email: str = 'lavalleevillage@stoneisland.com'
    legal_name: str = 'Stone Island France'
    vat_number: str = 'FR66897748F95'
    opens: str = '10:00'
    closes: str = '20:00'
    vat_rate: Decimal = Decimal('0.20')
    currency: str = 'EUR'
    timezone: str = 'Europe/Paris'
    consultants: tuple[str, ...] = ('Alexandre', 'Thomas', 'Louis', 'Sophie')

    @classmethod
    def from_env(cls):
        mapping = {'name': 'STORE_NAME', 'address_1': 'STORE_ADDRESS_1',
                   'address_2': 'STORE_ADDRESS_2', 'phone': 'STORE_PHONE',
                   'email': 'STORE_EMAIL', 'legal_name': 'STORE_LEGAL_NAME',
                   'vat_number': 'STORE_VAT_NUMBER', 'opens': 'STORE_OPEN',
                   'closes': 'STORE_CLOSE', 'timezone': 'STORE_TIMEZONE'}
        defaults = cls()
        values = {key: getenv(env, getattr(defaults, key)).strip() for key, env in mapping.items()}
        if any(len(value) > 120 for value in values.values()):
            raise ValueError('Реквизиты магазина: максимум 120 символов на поле.')
        ZoneInfo(values['timezone'])
        return cls(**values)
