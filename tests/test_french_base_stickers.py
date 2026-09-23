import json
import unittest
from datetime import date
from decimal import Decimal
from io import BytesIO
from PIL import Image
from bot.receipts.models import Receipt, ReceiptItem
from bot.receipts.config import StoreConfig
from bot.receipts.base_sticker import render_base_sticker, render_base_stickers


class BaseStickerTests(unittest.TestCase):
    def item(self, **changes):
        values = dict(quantity=2, name_it='FELPA', size='XXL', color='V0041', article='801563750',
                      unit_price=Decimal('170.50'), retail_price=Decimal('255.00'))
        return ReceiptItem(**{**values, **changes})

    def test_dimensions_payload_and_stability(self):
        item = self.item()
        png = render_base_sticker(item)
        image = Image.open(BytesIO(png))
        self.assertAlmostEqual(image.width / image.info['dpi'][0] * 25.4, 50, places=6)
        self.assertAlmostEqual(image.height / image.info['dpi'][1] * 25.4, 25, places=6)
        self.assertEqual(image.info['datamatrix_payload'], item.product_barcode + item.sticker_suffix)
        self.assertEqual(len(item.sticker_datamatrix), 25)
        self.assertEqual(json.loads(image.info['product']), item.to_dict())
        self.assertEqual(png, render_base_sticker(ReceiptItem.from_dict(item.to_dict())))

    def test_five_positions_have_distinct_stable_stickers(self):
        receipt = Receipt.create(date(2026, 9, 23), [self.item() for _ in range(5)], StoreConfig())
        stickers = render_base_stickers(receipt)
        self.assertEqual(len(stickers), 5)
        self.assertEqual(len(set(stickers)), 5)
        self.assertEqual(stickers, render_base_stickers(Receipt.from_dict(receipt.to_dict())))

    def test_service_field_validation(self):
        for key, value in [('sticker_serial', '123'), ('sticker_suffix', 'A' * 12), ('sticker_code', '1234')]:
            with self.assertRaises(ValueError): self.item(**{key: value})

    def test_maximum_fields_render(self):
        item = self.item(name_it='A' * 80, article='A' * 32, color='B' * 24, size='X' * 16)
        self.assertEqual(Image.open(BytesIO(render_base_sticker(item))).size, (1000, 500))

    def test_independent_decoder_reads_both_codes(self):
        try:
            import zxingcpp
        except ImportError:
            self.skipTest('Optional independent decoder zxingcpp is not installed')
        item = self.item()
        results = zxingcpp.read_barcodes(Image.open(BytesIO(render_base_sticker(item))))
        values = {result.text for result in results}
        self.assertIn(item.product_barcode, values)
        self.assertIn(item.sticker_datamatrix, values)
