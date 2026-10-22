import unittest

from money import split_amount


class TestSplitAmount(unittest.TestCase):
    def test_equal_split_gives_extra_cent_to_first(self):
        self.assertEqual(split_amount(100, [1, 1, 1]), [34, 33, 33])

    def test_largest_remainder(self):
        self.assertEqual(split_amount(100, [1, 2]), [33, 67])
        self.assertEqual(split_amount(7, [1, 1, 2]), [2, 2, 3])

    def test_two_leftover_cents(self):
        self.assertEqual(split_amount(10, [1, 1, 1, 1]), [3, 3, 2, 2])

    def test_leftover_larger_than_half_the_people(self):
        self.assertEqual(split_amount(5, [1] * 6), [1, 1, 1, 1, 1, 0])

    def test_exact_split(self):
        self.assertEqual(split_amount(1000, [3, 7]), [300, 700])

    def test_zero_total_and_zero_weight(self):
        self.assertEqual(split_amount(0, [1, 2]), [0, 0])
        self.assertEqual(split_amount(10, [0, 1, 1]), [0, 5, 5])

    def test_always_adds_up(self):
        for total in range(0, 60):
            for weights in ([1, 1, 1], [5, 3, 2], [1, 0, 7, 2], [9]):
                self.assertEqual(sum(split_amount(total, weights)), total, (total, weights))

    def test_invalid_input(self):
        for total, weights in ((10, []), (10, [0, 0]), (10, [1, -1]), (-5, [1, 1])):
            with self.assertRaises(ValueError):
                split_amount(total, weights)
