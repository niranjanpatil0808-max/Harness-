import unittest

from checkout import checkout_total

CART = [{"price": 40.0, "qty": 2}, {"price": 20.0, "qty": 1}]


class TestCheckout(unittest.TestCase):
    def test_no_code(self):
        self.assertEqual(checkout_total(CART), 105.0)

    def test_percent_coupon(self):
        self.assertEqual(checkout_total(CART, "WELCOME10"), 95.0)
        self.assertEqual(checkout_total(CART, "FESTIVE25"), 80.0)

    def test_unknown_code(self):
        self.assertEqual(checkout_total(CART, "BOGUS"), 105.0)
