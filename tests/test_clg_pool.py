import csv
import tempfile
import unittest
from pathlib import Path

from bot.services.clg_pool import ClgPair, ClgPool, parse_clg_pairs


class ClgPoolTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.pool = ClgPool(root / "clg.sqlite3", root / "отработка.csv")

    def tearDown(self):
        self.tempdir.cleanup()

    def test_parse_import_and_historical_duplicates(self):
        pairs, invalid = parse_clg_pairs(
            "783440262709, http://certilogo.com/qr/14GSH3AB5W\n"
            "плохая строка\n"
        )
        self.assertEqual(pairs, [ClgPair("783440262709", "http://certilogo.com/qr/14GSH3AB5W")])
        first = self.pool.import_pairs(pairs, invalid)
        self.assertEqual((first.added, first.duplicates, first.invalid), (1, 0, 1))

        token, reserved = self.pool.reserve(1)
        self.assertEqual(reserved, pairs)
        self.assertEqual(self.pool.consume(token, 123), 1)

        duplicate = self.pool.import_pairs(pairs)
        self.assertEqual((duplicate.added, duplicate.duplicates), (0, 1))
        self.assertEqual(self.pool.counts()["used"], 1)

    def test_duplicate_url_is_rejected_even_with_another_code(self):
        url = "http://certilogo.com/qr/14GSH3AB5W"
        result = self.pool.import_pairs([
            ClgPair("783440262709", url),
            ClgPair("111111111111", url),
        ])
        self.assertEqual((result.added, result.duplicates), (1, 1))

        protocol_variant = self.pool.import_pairs([
            ClgPair("222222222222", "https://www.certilogo.com/qr/14gsh3ab5w/")
        ])
        self.assertEqual((protocol_variant.added, protocol_variant.duplicates), (0, 1))

    def test_release_returns_item_to_available_pool(self):
        pair = ClgPair("783440262709", "http://certilogo.com/qr/14GSH3AB5W")
        self.pool.import_pairs([pair])
        token, _ = self.pool.reserve(1)
        self.pool.release(token)
        next_token, reserved = self.pool.reserve(1)
        self.assertTrue(next_token)
        self.assertEqual(reserved, [pair])

    def test_consume_exports_worked_csv(self):
        pair = ClgPair("783440262709", "http://certilogo.com/qr/14GSH3AB5W")
        self.pool.import_pairs([pair])
        token, _ = self.pool.reserve(1)
        self.pool.consume(token, 456)
        with self.pool.worked_path.open(encoding="utf-8-sig", newline="") as source:
            rows = list(csv.reader(source))
        self.assertEqual(rows[0][:2], ["12_значный_код", "ссылка"])
        self.assertEqual(rows[1][0:2], [pair.code, pair.url])
        self.assertEqual(rows[1][3], "456")


if __name__ == "__main__":
    unittest.main()
