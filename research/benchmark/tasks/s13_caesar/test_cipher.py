import unittest

from cipher import caesar


class TestCaesar(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(caesar("abc", 1), "bcd")

    def test_wrap(self):
        self.assertEqual(caesar("xyz", 3), "abc")

    def test_case_and_punctuation(self):
        self.assertEqual(caesar("Hello, World!", 5), "Mjqqt, Btwqi!")

    def test_negative(self):
        self.assertEqual(caesar("abc", -1), "zab")
