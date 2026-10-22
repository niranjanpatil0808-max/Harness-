import unittest

from pricing import order_summary


class TestOrderSummary(unittest.TestCase):
    def test_no_discount(self):
        s = order_summary([(10000, 2)], "IN")
        self.assertEqual(s, {"subtotal": 20000, "discount": 0, "tax": 3600, "total": 23600})

    def test_tax_is_charged_on_the_discounted_amount(self):
        s = order_summary([(10000, 2)], "IN", 60000)  # 10% loyalty discount
        self.assertEqual(s["discount"], 2000)
        self.assertEqual(s["tax"], 3240)
        self.assertEqual(s["total"], 21240)

    def test_other_region(self):
        s = order_summary([(5000, 1), (2500, 2)], "US", 250000)  # 15% discount
        self.assertEqual(s["subtotal"], 10000)
        self.assertEqual(s["discount"], 1500)
        self.assertEqual(s["tax"], 595)
        self.assertEqual(s["total"], 9095)
