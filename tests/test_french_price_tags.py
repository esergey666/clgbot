import json
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from PIL import Image
from bot.receipts.config import StoreConfig
from bot.receipts.models import Receipt, ReceiptItem
from bot.receipts.product_codes import check_digit, generate_product_barcode, validate_barcode
from bot.receipts.price_tag import render_price_tag, render_price_tags
from bot.receipts.renderer import layout


class FrenchPriceTagTests(unittest.TestCase):
    def item(self, **changes):
        values = dict(quantity=2, name_it='FELPA', size='XXL', color='V0041', article='801563750',
                      unit_price=Decimal('170.50'), retail_price=Decimal('255.00'))
        return ReceiptItem(**{**values, **changes})

    def test_ean_generation_and_check_digit(self):
        self.assertEqual(check_digit('805257298649'), '9')
        self.assertEqual(validate_barcode('8052572986499'), '8052572986499')
        codes = {generate_product_barcode() for _ in range(200)}
        self.assertEqual(len(codes), 200)
        for code in codes:
            self.assertEqual(validate_barcode(code), code)
        for code in ('8052572986490', '123', 'ABCDEFGHIJKLM'):
            with self.assertRaises(ValueError): validate_barcode(code)

    def test_receipt_uses_product_barcode_and_outlet_price(self):
        item = self.item()
        receipt = Receipt.create(date(2026, 9, 23), [item], StoreConfig())
        commands, _ = layout(receipt, StoreConfig())
        texts = [c[2] for c in commands if c[0] == 'text']
        self.assertIn(item.product_barcode, texts)
        self.assertNotIn(item.article, texts)
        self.assertEqual(receipt.total_ttc, Decimal('341.00'))
        self.assertEqual(item.retail_price, Decimal('255.00'))

    def test_exact_tag_dimensions_and_data_round_trip(self):
        item = self.item()
        image = Image.open(BytesIO(render_price_tag(item)))
        self.assertAlmostEqual(image.width / image.info['dpi'][0] * 25.4, 50, places=6)
        self.assertAlmostEqual(image.height / image.info['dpi'][1] * 25.4, 25, places=6)
        self.assertEqual(json.loads(image.info['product']), item.to_dict())
        restored = ReceiptItem.from_dict(item.to_dict())
        self.assertEqual(render_price_tag(restored), render_price_tag(item))

    def test_five_positions_have_five_tags(self):
        items = [self.item() for _ in range(5)]
        receipt = Receipt.create(date(2026, 9, 23), items, StoreConfig())
        tags = render_price_tags(receipt)
        self.assertEqual(len(tags), 5)
        for item, png in zip(items, tags):
            data = json.loads(Image.open(BytesIO(png)).info['product'])
            self.assertEqual(data['product_barcode'], item.product_barcode)
            self.assertEqual(data['unit_price'], '170.50')
            self.assertEqual(data['retail_price'], '255.00')

    def test_maximum_length_fields_fit(self):
        item = self.item(name_it='GIUBBOTTO ' + 'A' * 70, article='A' * 32, color='B' * 24,
                         size='X' * 16, unit_price=Decimal('9999999.99'), retail_price=Decimal('9999999.99'))
        self.assertEqual(Image.open(BytesIO(render_price_tag(item))).size, (1000, 500))

    def test_outlet_price_cannot_exceed_retail(self):
        with self.assertRaises(ValueError): self.item(retail_price=Decimal('100.00'))
