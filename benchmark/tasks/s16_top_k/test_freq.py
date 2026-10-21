import unittest

from freq import top_k


class TestTopK(unittest.TestCase):
    def test_counts(self):
        self.assertEqual(top_k(["a", "b", "a", "c", "a", "b"], 2), ["a", "b"])

    def test_ties_alphabetical(self):
        self.assertEqual(top_k(["pear", "apple", "fig", "apple", "pear", "fig"], 3), ["apple", "fig", "pear"])

    def test_k_larger(self):
        self.assertEqual(top_k(["x"], 5), ["x"])
