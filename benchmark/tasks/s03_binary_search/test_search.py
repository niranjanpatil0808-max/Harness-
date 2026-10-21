import unittest

from search import binary_search


class TestBinarySearch(unittest.TestCase):
    def test_found_each_position(self):
        items = [1, 3, 5, 7, 9]
        for index, value in enumerate(items):
            self.assertEqual(binary_search(items, value), index)

    def test_missing(self):
        self.assertEqual(binary_search([1, 3, 5], 4), -1)

    def test_single(self):
        self.assertEqual(binary_search([42], 42), 0)

    def test_empty(self):
        self.assertEqual(binary_search([], 1), -1)
