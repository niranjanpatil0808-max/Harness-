import unittest

from series import moving_average


class TestMovingAverage(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(moving_average([1, 2, 3, 4, 5], 2), [1.5, 2.5, 3.5, 4.5])

    def test_window_equals_length(self):
        self.assertEqual(moving_average([2, 4, 6], 3), [4.0])

    def test_too_short(self):
        self.assertEqual(moving_average([1, 2], 3), [])
