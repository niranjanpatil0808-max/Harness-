import unittest

from users import display_name


class TestDisplayName(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(display_name({"first": "ada", "last": "LOVELACE"}), "Ada Lovelace")

    def test_small_words(self):
        self.assertEqual(display_name({"first": "ludwig", "middle": "van", "last": "beethoven"}),
                         "Ludwig van Beethoven")

    def test_small_word_first(self):
        self.assertEqual(display_name({"first": "the", "last": "rock of gibraltar"}), "The Rock of Gibraltar")
