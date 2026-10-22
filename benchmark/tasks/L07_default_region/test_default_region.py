import unittest

from taxes import tax_for, tax_rate_bps


class TestDefaultRegion(unittest.TestCase):
    def test_known_regions(self):
        self.assertEqual(tax_rate_bps("US"), 700)
        self.assertEqual(tax_rate_bps("EU"), 2000)

    def test_unknown_region_uses_the_default_rate(self):
        self.assertEqual(tax_rate_bps("XX"), 1800)
        self.assertEqual(tax_rate_bps(""), 1800)

    def test_tax_for_unknown_region(self):
        self.assertEqual(tax_for(1000, "XX"), 180)
