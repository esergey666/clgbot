import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from bot.services import image_label_recognizer as ocr


class RecognitionTests(unittest.TestCase):
    def test_45mm_proc_from_reported_photo(self):
        text = 'Art.\nK2S15Q100004S0B22\nV0061\nTg. M\n99PROC20250003146'
        self.assertEqual(ocr._extract_first_photo(text, 'clg2026'),
                         ('K2S15Q100004S0B22', 'V0061', 'M', '99PROC20250003146'))

    def test_45mm_proc_ocr_variants(self):
        for text in ('99PR0C20250003146', '99PROC\n20250003146', '99-PROC20250003146'):
            with self.subTest(text=text):
                self.assertEqual(ocr._extract_first_photo(text, 'clg2026')[3], '99PROC20250003146')

    def test_45mm_preserves_batch_variant(self):
        for variant in ('C', 'I', 'M'):
            code = '99PRO' + variant + '20250003146'
            self.assertEqual(ocr._normalize_45mm_batch_code(code), code)

    def test_40mm_spacing_and_zero(self):
        self.assertEqual(ocr._extract_first_photo('ART: 801 564 651\nCOL: V0029\nTG. XL\nT0M 068804'), ('801564651', 'V0029', 'XL', 'TOM068804'))

    def test_45mm_split_fourth_line(self):
        self.assertEqual(ocr._extract_first_photo('ART K1234567890123456\nCOL V0029\nTG XXL\n99PR01\n20250007668', 'clg2026'), ('K1234567890123456', 'V0029', 'XXL', '99PROI20250007668'))

    def test_unrelated_lines_not_joined(self):
        self.assertEqual(ocr._extract_first_photo('12345\n6789')[0], '')

    def test_original_always_included(self):
        image = Image.new('RGB', (100, 200), 'red')
        stream = BytesIO(); image.save(stream, format='PNG')
        with patch.object(ocr, '_label_region_candidates', return_value=[Image.new('L', (100, 200), 255)]):
            candidates = ocr._rapidocr_candidate_bytes(stream.getvalue())
        self.assertEqual(Image.open(BytesIO(candidates[0])).getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(len(candidates), 4)

    def test_partial_rapid_result_uses_fallback(self):
        with patch.object(ocr, '_ocr_text', side_effect=['ART 801564651\nCOL V0029\nTG XL', 'CLG783440262709']), patch.object(ocr, '_read_qr', return_value='http://certilogo.com/qr/ABC1234567'), patch.object(ocr, '_tesseract_text', return_value='TOM068804') as fallback:
            result = ocr._recognize_label_photos_sync(first_photo=b'a', second_photo=b'b')
        self.assertEqual(result.code, 'TOM068804')
        fallback.assert_called_once_with(b'a')


if __name__ == '__main__':
    unittest.main()
