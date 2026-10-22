import unittest

from taxes import price_with_tax, tax_for


class TestTaxRounding(unittest.TestCase):
    def test_rounds_half_up_not_down(self):
        self.assertEqual(tax_for(999, "IN"), 180)   # 179.82 -> 180
        self.assertEqual(tax_for(25, "US"), 2)      # 1.75 -> 2

    def test_small_amounts(self):
        self.assertEqual(tax_for(1, "US"), 0)       # 0.07 -> 0
        self.assertEqual(tax_for(5, "EU"), 1)       # exactly 1

    def test_exact(self):
        self.assertEqual(tax_for(1000, "US"), 70)

    def test_price_with_tax(self):
        self.assertEqual(price_with_tax(999, "IN"), 1179)
