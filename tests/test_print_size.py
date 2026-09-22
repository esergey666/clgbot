import asyncio
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
from PIL import Image
from bot.services.label_generator import LabelGenerator

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


class PrintSizeTests(unittest.TestCase):
    def generator(self, scale=1):
        return LabelGenerator(ASSETS / 'back.png', ASSETS / 'font.ttf',
                              ASSETS / 'num.ttf', ASSETS / 'maket.jpg', scale=scale)

    def assert_print_size(self, output):
        output.seek(0)
        with Image.open(output) as image:
            dpi_x, dpi_y = image.info['dpi']
            self.assertAlmostEqual(image.width / dpi_x * 25.4, 40, places=3)
            self.assertAlmostEqual(image.height / dpi_y * 25.4, 165, places=3)

    def test_saved_png_has_fixed_physical_dimensions_at_each_scale(self):
        for scale in (1, 2):
            with self.subTest(scale=scale):
                generator = self.generator(scale)
                output = BytesIO()
                output.name = 'label.png'
                asyncio.run(generator.save(output))
                self.assert_print_size(output)
                self.assertEqual(generator.template.size, (1200 * scale, 4950 * scale))

    def test_generated_png_has_fixed_physical_dimensions(self):
        generator = self.generator()
        # Matrix encoding is independent of PNG print metadata and needs a native DLL.
        generator.add_datemark = AsyncMock()
        generator.add_qr = AsyncMock()
        output = asyncio.run(generator.generate_label('801563051', 'A0M64', 'M',
                                                      'TOM079762', '169 240 650 854',
                                                      'http://certilogo.com/qr/004O4C5UEB'))
        self.assert_print_size(output)
