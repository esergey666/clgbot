import unittest
import json
from datetime import date, datetime, time
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
from PIL import Image, ImageFont
from bot.receipts.calculations import parse_price, parse_quantity, parse_date, money, totals, cash_payment
from bot.receipts.config import StoreConfig
from bot.receipts.models import Receipt, ReceiptItem
from bot.receipts.id_generator import purchase_time
from bot.receipts.renderer import render, wrap_text, layout, ASSETS
from bot.receipts.barcode_qr import qr_payload


def item(quantity=1, price='395', name='GIUBBOTTO SENZA MANICHE'):
    return ReceiptItem(quantity, name, 'XXL', 'NERO', '8115G0123', Decimal(price))


def receipt(items):
    return Receipt.create(date(2026, 9, 23), items, StoreConfig())


class ReceiptTests(unittest.TestCase):
    def test_quantity_and_totals(self):
        one = receipt([item()]); self.assertEqual(one.total_ttc, Decimal('395.00'))
        result = receipt([item(), item(2, '170.50', 'FELPA CON CAPPUCCIO')])
        self.assertEqual(result.total_ttc, Decimal('736.00'))
        self.assertEqual(result.total_ht, Decimal('613.33'))
        self.assertEqual(result.vat_amount, Decimal('122.67'))
        self.assertEqual(result.article_count, 3)
        self.assertEqual(result.items[1].line_total, Decimal('341.00'))

    def test_french_vat_example(self):
        result = receipt([item(), item(1, '170.50')])
        self.assertEqual((result.total_ttc, result.total_ht, result.vat_amount),
                         (Decimal('565.50'), Decimal('471.25'), Decimal('94.25')))

    def test_price_and_rounding(self):
        for value in ('395.50', '395,50', '395.5'):
            self.assertEqual(parse_price(value), Decimal('395.50'))
        self.assertEqual(parse_price('395'), Decimal('395.00'))
        self.assertEqual(money(Decimal('1.005')), Decimal('1.01'))
        for value in ('NaN', 'Infinity', '-1', 'abc', '1e3', '1.001'):
            with self.assertRaises(ValueError): parse_price(value)

    def test_invalid_items_and_dates(self):
        for value in ('0', '-1', '1.2', 'abc'):
            with self.assertRaises(ValueError): parse_quantity(value)
        with self.assertRaises(ValueError): parse_date('31.02.2026')
        with self.assertRaises(ValueError): item(name='')
        with self.assertRaises(ValueError): ReceiptItem(1, 'FELPA', 'L', 'NERO', '', Decimal('1'))
        with self.assertRaises(ValueError): receipt([])
        with self.assertRaises(ValueError): receipt([item()] * 21)

    def test_today_and_working_hours(self):
        from zoneinfo import ZoneInfo
        self.assertEqual(parse_date(''), datetime.now(ZoneInfo('Europe/Paris')).date())
        with patch('bot.receipts.id_generator.secrets.randbelow', return_value=0):
            self.assertEqual(purchase_time('10:00', '20:00'), time(10, 0))
        with patch('bot.receipts.id_generator.secrets.randbelow', return_value=36000):
            self.assertEqual(purchase_time('10:00', '20:00'), time(20, 0))
        for _ in range(100): self.assertTrue(time(10) <= purchase_time('10:00', '20:00') <= time(20))
        with self.assertRaises(ValueError): purchase_time('20:00', '10:00')

    def test_unique_ids_and_serialization(self):
        ids = {receipt([item()]).receipt_id for _ in range(200)}
        self.assertEqual(len(ids), 200)
        result = receipt([item()])
        self.assertEqual(Receipt.from_dict(json.loads(json.dumps(result.to_dict()))), result)
        self.assertEqual(json.loads(qr_payload(result))['total'], '395.00')

    def test_change(self):
        self.assertEqual(cash_payment(Decimal('565.50')), (Decimal('600.00'), Decimal('34.50')))
        self.assertEqual(cash_payment(Decimal('100.00')), (Decimal('100.00'), Decimal('0.00')))

    def test_long_names_wrap_without_loss(self):
        font = ImageFont.truetype(str(ASSETS / 'arial.ttf'), 30)
        name = 'GIUBBOTTO ' + 'A' * 70
        lines = wrap_text(name, font, 300)
        self.assertEqual(''.join(lines).replace(' ', ''), name.replace(' ', ''))
        self.assertTrue(all(font.getlength(line) <= 300 for line in lines))

    def test_variable_length_png(self):
        heights = []
        for count in (1, 2, 3, 20):
            result = receipt([item(name='FELPA')] * count)
            image = Image.open(BytesIO(render(result, StoreConfig())))
            self.assertEqual(image.width, 945)
            self.assertAlmostEqual(image.info['dpi'][0], 300, places=1)
            heights.append(image.height)
        self.assertEqual(heights[1], 2244)
        self.assertEqual(heights, sorted(set(heights)))

    def test_twenty_long_items_fit(self):
        result = receipt([item(2, name='GIUBBOTTO ' + 'L' * 70)] * 20)
        commands, height = layout(result, StoreConfig(), 30)
        for command in commands:
            if command[0] == 'text':
                _, (x, y), text, font = command
                self.assertGreaterEqual(x, 0)
                self.assertLessEqual(x + font.getlength(text), 945)
                self.assertLess(y + 40, height)
