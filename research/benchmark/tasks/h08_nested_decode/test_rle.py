import unittest

from rle import decode


class TestDecode(unittest.TestCase):
    def test_plain_and_empty(self):
        self.assertEqual(decode("abc"), "abc")
        self.assertEqual(decode(""), "")

    def test_repeated_letter(self):
        self.assertEqual(decode("3a"), "aaa")
        self.assertEqual(decode("2ab"), "aab")
        self.assertEqual(decode("12a"), "a" * 12)

    def test_group(self):
        self.assertEqual(decode("2(ab)"), "abab")
        self.assertEqual(decode("2(a)3(b)"), "aabbb")
        self.assertEqual(decode("1(x)"), "x")

    def test_nested_groups(self):
        self.assertEqual(decode("3(ab2(c))"), "abccabccabcc")
        self.assertEqual(decode("2(2(2a))"), "a" * 8)

    def test_zero_count(self):
        self.assertEqual(decode("0(abc)d"), "d")
        self.assertEqual(decode("0ab"), "b")

    def test_unbalanced(self):
        for bad in ("2(ab", "ab)", "2(a2(b)"):
            with self.assertRaises(ValueError, msg=bad):
                decode(bad)

    def test_number_without_target(self):
        for bad in ("3", "3)", "2(a)4"):
            with self.assertRaises(ValueError, msg=bad):
                decode(bad)

    def test_group_without_count_and_other_characters(self):
        for bad in ("(ab)", "a b", "2(a-b)"):
            with self.assertRaises(ValueError, msg=bad):
                decode(bad)
