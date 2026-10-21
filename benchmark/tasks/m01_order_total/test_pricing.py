import unittest

from pricing import order_total


class TestOrderTotal(unittest.TestCase):
    def test_includes_tax(self):
        self.assertEqual(order_total([(10.0, 2), (5.0, 1)]), 27.0)

    def test_empty(self):
        self.assertEqual(order_total([]), 0)
