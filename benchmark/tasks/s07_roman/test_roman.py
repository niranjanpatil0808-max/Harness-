import unittest

from roman import roman_to_int


class TestRoman(unittest.TestCase):
    def test_additive(self):
        self.assertEqual(roman_to_int("XVI"), 16)

    def test_subtractive(self):
        self.assertEqual(roman_to_int("IV"), 4)
        self.assertEqual(roman_to_int("XC"), 90)

    def test_mixed(self):
        self.assertEqual(roman_to_int("MCMXCIV"), 1994)
