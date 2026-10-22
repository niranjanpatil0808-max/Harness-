import unittest

from fib import fib


class TestFib(unittest.TestCase):
    def test_base(self):
        self.assertEqual(fib(0), 0)
        self.assertEqual(fib(1), 1)

    def test_sequence(self):
        self.assertEqual([fib(i) for i in range(10)], [0, 1, 1, 2, 3, 5, 8, 13, 21, 34])
