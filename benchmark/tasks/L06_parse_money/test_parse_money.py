import unittest

from money import parse_money


class TestParseMoney(unittest.TestCase):
    def test_floating_point_traps(self):
        self.assertEqual(parse_money("19.99"), 1999)
        self.assertEqual(parse_money("0.07"), 7)
        self.assertEqual(parse_money("1.15"), 115)

    def test_symbols_and_commas(self):
        self.assertEqual(parse_money("$1,234.50"), 123450)
        self.assertEqual(parse_money("  42  "), 4200)

    def test_half_cents_round_up(self):
        self.assertEqual(parse_money("1.005"), 101)
        self.assertEqual(parse_money("2.675"), 268)
