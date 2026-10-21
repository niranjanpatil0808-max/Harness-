import unittest

from dedupe import dedupe


class TestDedupe(unittest.TestCase):
    def test_order_kept(self):
        self.assertEqual(dedupe([3, 1, 3, 2, 1]), [3, 1, 2])

    def test_strings(self):
        self.assertEqual(dedupe(["b", "a", "b", "c", "a"]), ["b", "a", "c"])

    def test_empty(self):
        self.assertEqual(dedupe([]), [])
