import unittest

from brackets import is_balanced


class TestBalanced(unittest.TestCase):
    def test_balanced(self):
        self.assertTrue(is_balanced("f(a[1], {b: 2})"))

    def test_wrong_type(self):
        self.assertFalse(is_balanced("(]"))

    def test_unclosed(self):
        self.assertFalse(is_balanced("(("))

    def test_extra_close(self):
        self.assertFalse(is_balanced("())"))
