import unittest

from inventory import Stock


class TestLowStock(unittest.TestCase):
    def test_at_the_threshold_is_low(self):
        stock = Stock()
        stock.add("A", 5)
        stock.add("B", 6)
        self.assertEqual(stock.low_stock(), ["A"])

    def test_reserved_units_do_not_count_as_available(self):
        stock = Stock()
        stock.add("A", 5)
        stock.add("B", 6)
        stock.reserve("B", 2)
        self.assertEqual(stock.low_stock(), ["A", "B"])

    def test_plenty_of_stock(self):
        stock = Stock()
        stock.add("C", 100)
        self.assertEqual(stock.low_stock(), [])
