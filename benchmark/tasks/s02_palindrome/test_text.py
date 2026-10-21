import unittest

from text import is_palindrome


class TestPalindrome(unittest.TestCase):
    def test_simple(self):
        self.assertTrue(is_palindrome("Racecar"))

    def test_punctuation(self):
        self.assertTrue(is_palindrome("A man, a plan, a canal: Panama!"))

    def test_not_palindrome(self):
        self.assertFalse(is_palindrome("hello, world"))

    def test_empty(self):
        self.assertTrue(is_palindrome(""))
