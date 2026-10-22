import unittest

from money import format_money


class TestFormatMoney(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(format_money(123456), "1,234.56")
        self.assertEqual(format_money(5), "0.05")
        self.assertEqual(format_money(0), "0.00")

    def test_negative(self):
        self.assertEqual(format_money(-5), "-0.05")
        self.assertEqual(format_money(-123456), "-1,234.56")
        self.assertEqual(format_money(-100), "-1.00")
