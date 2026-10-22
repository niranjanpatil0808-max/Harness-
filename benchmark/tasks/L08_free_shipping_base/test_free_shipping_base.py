import unittest

from orders import checkout


class TestCheckout(unittest.TestCase):
    def test_small_order_pays_shipping(self):
        c = checkout([(10000, 1)], 300, "IN")
        self.assertEqual(c["shipping"], 4000)
        self.assertEqual(c["grand_total"], c["total"] + 4000)

    def test_free_shipping_is_judged_on_the_subtotal_before_discount(self):
        # subtotal 520000 reaches the free-shipping minimum even though the discounted
        # total (with tax) ends up below it.
        c = checkout([(260000, 2)], 500, "US", 250000)
        self.assertEqual(c["total"], 472940)
        self.assertEqual(c["shipping"], 0)
        self.assertEqual(c["grand_total"], 472940)

    def test_heavy_order_below_the_minimum(self):
        c = checkout([(20000, 3)], 6000, "EU")
        self.assertEqual(c["shipping"], 30000)
