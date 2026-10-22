import unittest

from pipeline import slugify


class TestSlugify(unittest.TestCase):
    def test_words(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_numbers_kept(self):
        self.assertEqual(slugify("Top 10 Tips for 2026"), "top-10-tips-for-2026")
