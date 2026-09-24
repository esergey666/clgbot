import unittest
import json
import base64
import re
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
    def test_synthetic_scan_style_codes_and_cashier(self):
        result = Receipt.create(date(2026, 9, 23), [item()], StoreConfig(consultants=('Camille',)))
        self.assertEqual(result.cashier_name, 'Camille')
        self.assertEqual(result.display_cashier, 'Camille')
        self.assertRegex(result.barcode_value, r'^01B\d{10}$')
        self.assertEqual(len(result.control_code), 96)
        self.assertEqual(len(base64.b64decode(result.control_code, validate=True)), 72)
        restored = Receipt.from_dict(result.to_dict())
        self.assertEqual(restored.barcode_data, result.barcode_data)
        self.assertEqual(restored.control_code, result.control_code)
        self.assertEqual(render(restored, StoreConfig()), render(result, StoreConfig()))

    def test_cashier_configuration(self):
        with patch.dict('os.environ', {'STORE_CASHIERS': 'Camille, Pierre'}):
            self.assertEqual(StoreConfig.from_env().consultants, ('Camille', 'Pierre'))
        with patch.dict('os.environ', {'STORE_CASHIERS': ' , '}):
            with self.assertRaises(ValueError): StoreConfig.from_env()

    def test_old_receipt_has_stable_fallback_barcode(self):
        data = receipt([item()]).to_dict()
        data.pop('cashier_name'); data.pop('barcode_value')
        old = Receipt.from_dict(data)
        self.assertEqual(old.display_cashier, old.consultant_name)
        self.assertRegex(old.barcode_data, r'^01B\d{10}$')
        self.assertEqual(Receipt.from_dict(old.to_dict()).barcode_data, old.barcode_data)

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

    def test_reference_layout_and_png_metadata(self):
        result = receipt([item(), item(1, '170.50')])
        commands, _ = layout(result, StoreConfig())
        texts = [command[2] for command in commands if command[0] == 'text']
        for label in ('Numero', 'Etab', 'Caisse', 'Vd', 'Montant', 'Taux', 'Base HT', 'A01'):
            self.assertIn(label, texts)
        self.assertFalse(any(command[0] == 'qr' for command in commands))
        image = Image.open(BytesIO(render(result, StoreConfig())))
        self.assertEqual(json.loads(image.info['receipt']), result.to_dict())
        self.assertEqual(json.loads(image.info['receipt_qr_payload'])['receipt_id'], result.receipt_id)

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
        commands, height = layout(result, StoreConfig())
        for command in commands:
            if command[0] == 'text':
                _, (x, y), text, font = command
                self.assertGreaterEqual(x, 0)
                self.assertLessEqual(x + font.getlength(text), 945)
                self.assertLess(y + 40, height)

    def test_item_description_crops_like_reference_without_changing_data(self):
        product = ReceiptItem(1, 'GIUBBOTTO SENZA MANICHE', 'XXL', 'V0029', '8115G0123', Decimal('395'))
        result = receipt([product])
        commands, height = layout(result, StoreConfig())
        descriptions = [c for c in commands if c[0] == 'text' and c[1][0] == 100 and c[3].font.size == 50]
        self.assertEqual(len(descriptions), 1)
        self.assertEqual(descriptions[0][2], 'GIUBBOTTO SENZA MANICHE X')
        texts = [c[2] for c in commands if c[0] == 'text']
        self.assertNotIn('V0029', texts)
        self.assertIn(product.product_barcode, texts)
        self.assertIn('395,00', texts)
        self.assertEqual(height, layout(receipt([item(name='FELPA')]), StoreConfig())[1])
        data = json.loads(Image.open(BytesIO(render(result, StoreConfig()))).info['receipt'])['items'][0]
        self.assertEqual(data['name_it'], product.name_it)
        self.assertEqual(data['size'], 'XXL')
        self.assertEqual(data['color'], 'V0029')

    def test_truncation_boundary_and_amount_space(self):
        from bot.receipts.renderer import item_description, font_style
        style = font_style(50)
        for count in (24, 25, 26, 80):
            product = ReceiptItem(1, 'A' * count, '-', '-', '123', Decimal('1'))
            self.assertEqual(item_description(product, style, 600), 'A' * min(count, 25))
        product = item(name='A' * 80)
        value = item_description(product, style, 185)
        self.assertLessEqual(style.getlength(value), 185)
        self.assertGreater(style.getlength(value + 'A'), 185)
        self.assertNotIn('…', value)
