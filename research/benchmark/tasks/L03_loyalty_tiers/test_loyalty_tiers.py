import unittest

from customers import loyalty_discount_bps


class TestLoyalty(unittest.TestCase):
    def test_new_customer(self):
        self.assertEqual(loyalty_discount_bps(0), 0)
        self.assertEqual(loyalty_discount_bps(9999), 0)

    def test_exactly_reaching_a_tier_counts(self):
        self.assertEqual(loyalty_discount_bps(10000), 500)
        self.assertEqual(loyalty_discount_bps(50000), 1000)
        self.assertEqual(loyalty_discount_bps(200000), 1500)

    def test_between_tiers(self):
        self.assertEqual(loyalty_discount_bps(49999), 500)
        self.assertEqual(loyalty_discount_bps(150000), 1000)
        self.assertEqual(loyalty_discount_bps(10**9), 1500)
