import unittest

from inventory import Stock


class TestReserve(unittest.TestCase):
    def test_reserving_reduces_availability(self):
        stock = Stock()
        stock.add("X", 10)
        stock.reserve("X", 4)
        self.assertEqual(stock.available("X"), 6)

    def test_cannot_reserve_more_than_available(self):
        stock = Stock()
        stock.add("X", 10)
        stock.reserve("X", 4)
        with self.assertRaises(ValueError):
            stock.reserve("X", 7)
        stock.reserve("X", 6)
        self.assertEqual(stock.available("X"), 0)
        with self.assertRaises(ValueError):
            stock.reserve("X", 1)

    def test_release_gives_units_back(self):
        stock = Stock()
        stock.add("X", 3)
        stock.reserve("X", 3)
        stock.release("X", 2)
        self.assertEqual(stock.available("X"), 2)
