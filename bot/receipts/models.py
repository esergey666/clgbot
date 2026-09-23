from dataclasses import dataclass, asdict, field
from datetime import date, time
from decimal import Decimal

from .calculations import money, totals, cash_payment
from .config import StoreConfig
from .id_generator import identifiers, purchase_time
from .product_codes import generate_product_barcode, validate_barcode


@dataclass(frozen=True)
class ReceiptItem:
    quantity: int
    name_it: str
    size: str
    color: str
    article: str
    unit_price: Decimal
    retail_price: Decimal | None = None
    product_barcode: str = field(default_factory=generate_product_barcode)

    def __post_init__(self):
        if type(self.quantity) is not int or not 1 <= self.quantity <= 999:
            raise ValueError('Количество: от 1 до 999.')
        for field, maximum in (('name_it', 80), ('size', 16), ('color', 24), ('article', 32)):
            value = getattr(self, field).strip()
            if not value or len(value) > maximum or any(ord(c) < 32 for c in value):
                raise ValueError(f'{field}: от 1 до {maximum} символов, без переносов строк.')
            object.__setattr__(self, field, value)
        if not isinstance(self.unit_price, Decimal) or not self.unit_price.is_finite() or not 0 <= self.unit_price <= Decimal('9999999.99'):
            raise ValueError('Некорректная цена.')
        object.__setattr__(self, 'unit_price', money(self.unit_price))
        retail = self.unit_price if self.retail_price is None else self.retail_price
        if not isinstance(retail, Decimal) or not retail.is_finite() or not self.unit_price <= retail <= Decimal('9999999.99'):
            raise ValueError('Цена аутлета не должна превышать полную стоимость вещи.')
        object.__setattr__(self, 'retail_price', money(retail))
        validate_barcode(self.product_barcode)

    @property
    def line_total(self):
        return money(self.unit_price * self.quantity)

    def to_dict(self):
        return {**asdict(self), 'unit_price': str(self.unit_price), 'retail_price': str(self.retail_price)}

    @classmethod
    def from_dict(cls, data):
        return cls(**{**data, 'unit_price': Decimal(data['unit_price']),
                      'retail_price': Decimal(data.get('retail_price') or data['unit_price'])})


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    purchase_date: date
    purchase_time: time
    items: tuple[ReceiptItem, ...]
    total_ttc: Decimal
    total_ht: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    cash_paid: Decimal
    change: Decimal
    receipt_number: str
    establishment_id: str
    register_id: str
    sale_id: str
    seller_number: str
    consultant_name: str
    document_id: str
    control_code: str
    currency: str = 'EUR'
    barcode_value: str = ''
    cashier_name: str = ''

    @property
    def display_cashier(self):
        return self.cashier_name or self.consultant_name

    @property
    def barcode_data(self):
        if self.barcode_value:
            return self.barcode_value
        # Old in-progress receipts retain a stable barcode after an upgrade.
        import hashlib
        number = int(hashlib.sha256(self.receipt_id.encode()).hexdigest()[:16], 16) % 10**10
        return f'01B{number:010d}'

    @property
    def article_count(self):
        return sum(item.quantity for item in self.items)

    @classmethod
    def create(cls, day: date, items, store: StoreConfig):
        if not 1 <= len(items) <= 20:
            raise ValueError('В чеке должно быть от 1 до 20 позиций.')
        ttc, ht, vat = totals(items, store.vat_rate)
        paid, change = cash_payment(ttc)
        return cls(**identifiers(day, store.consultants), purchase_date=day,
                   purchase_time=purchase_time(store.opens, store.closes), items=tuple(items),
                   total_ttc=ttc, total_ht=ht, vat_rate=store.vat_rate, vat_amount=vat,
                   cash_paid=paid, change=change, currency=store.currency)

    def to_dict(self):
        data = asdict(self)
        data['items'] = [item.to_dict() for item in self.items]
        data['purchase_date'] = self.purchase_date.isoformat()
        data['purchase_time'] = self.purchase_time.isoformat()
        for field in ('total_ttc', 'total_ht', 'vat_rate', 'vat_amount', 'cash_paid', 'change'):
            data[field] = str(data[field])
        return data

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data['items'] = tuple(ReceiptItem.from_dict(item) for item in data['items'])
        data['purchase_date'] = date.fromisoformat(data['purchase_date'])
        data['purchase_time'] = time.fromisoformat(data['purchase_time'])
        for field in ('total_ttc', 'total_ht', 'vat_rate', 'vat_amount', 'cash_paid', 'change'):
            data[field] = Decimal(data[field])
        return cls(**data)

