import unittest

from words import word_count


class TestWordCount(unittest.TestCase):
    def test_case(self):
        self.assertEqual(word_count("The the THE"), {"the": 3})

    def test_punctuation(self):
        self.assertEqual(word_count("Hello, world! Hello."), {"hello": 2, "world": 1})

    def test_lone_punctuation_ignored(self):
        self.assertEqual(word_count("yes - no"), {"yes": 1, "no": 1})
