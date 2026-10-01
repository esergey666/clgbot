import unittest

from bot.handlers.label import _parse_user_label_list


class LabelListParsingTests(unittest.TestCase):
    def test_permanent_user_can_supply_own_clg_data(self):
        line = (
            "K2S15Q100004S0B22, V0029, 3X, 99PROC20250003146, "
            "365992529190, http://certilogo.com/qr/04IYDQQ5UF"
        )

        self.assertEqual(
            _parse_user_label_list(line, 4, allow_custom_clg=True),
            [[
                "K2S15Q100004S0B22",
                "V0029",
                "3X",
                "99PROC20250003146",
                "365992529190",
                "http://certilogo.com/qr/04IYDQQ5UF",
            ]],
        )

    def test_regular_user_cannot_supply_own_clg_data(self):
        with self.assertRaises(ValueError):
            _parse_user_label_list("A, B, C, D, 123456789012, http://example.com", 4)

    def test_four_and_six_field_rows_cannot_be_mixed(self):
        with self.assertRaisesRegex(ValueError, "нельзя смешивать"):
            _parse_user_label_list(
                "A, B, C, D\nA, B, C, D, 123456789012, http://example.com",
                4,
                allow_custom_clg=True,
            )


if __name__ == "__main__":
    unittest.main()
