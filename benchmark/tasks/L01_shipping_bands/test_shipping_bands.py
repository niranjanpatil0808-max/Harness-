import unittest

from shipping import shipping_cost


class TestShippingBands(unittest.TestCase):
    def test_band_edges_belong_to_the_lower_band(self):
        self.assertEqual(shipping_cost(500, 1000), 4000)
        self.assertEqual(shipping_cost(2000, 1000), 8000)
        self.assertEqual(shipping_cost(5000, 1000), 15000)

    def test_just_over_an_edge_moves_up(self):
        self.assertEqual(shipping_cost(501, 1000), 8000)
        self.assertEqual(shipping_cost(2001, 1000), 15000)
        self.assertEqual(shipping_cost(5001, 1000), 30000)

    def test_light_parcel(self):
        self.assertEqual(shipping_cost(1, 1000), 4000)

    def test_free_shipping(self):
        self.assertEqual(shipping_cost(9000, 500000), 0)
        self.assertEqual(shipping_cost(100, 499999), 4000)
