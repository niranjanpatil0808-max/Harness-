import unittest

from intervals import merge_intervals


class TestMerge(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 6], [8, 10]]), [[1, 6], [8, 10]])

    def test_touching(self):
        self.assertEqual(merge_intervals([[1, 2], [2, 4]]), [[1, 4]])

    def test_unsorted(self):
        self.assertEqual(merge_intervals([[8, 9], [1, 4], [3, 5]]), [[1, 5], [8, 9]])

    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
