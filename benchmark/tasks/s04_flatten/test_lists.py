import unittest

from lists import flatten


class TestFlatten(unittest.TestCase):
    def test_one_level(self):
        self.assertEqual(flatten([1, [2, 3], 4]), [1, 2, 3, 4])

    def test_deep(self):
        self.assertEqual(flatten([1, [2, [3, [4, [5]]]]]), [1, 2, 3, 4, 5])

    def test_empty_lists(self):
        self.assertEqual(flatten([[], [[]], 1]), [1])
