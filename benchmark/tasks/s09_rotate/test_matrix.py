import unittest

from matrix import rotate_clockwise


class TestRotate(unittest.TestCase):
    def test_square(self):
        self.assertEqual(rotate_clockwise([[1, 2], [3, 4]]), [[3, 1], [4, 2]])

    def test_rectangular(self):
        self.assertEqual(rotate_clockwise([[1, 2, 3], [4, 5, 6]]), [[4, 1], [5, 2], [6, 3]])

    def test_empty(self):
        self.assertEqual(rotate_clockwise([]), [])
