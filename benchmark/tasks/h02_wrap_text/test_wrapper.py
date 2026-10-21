import unittest

from wrapper import wrap_text


class TestWrapText(unittest.TestCase):
    def test_greedy(self):
        self.assertEqual(wrap_text("the quick brown fox", 10), ["the quick", "brown fox"])

    def test_exact_fit(self):
        self.assertEqual(wrap_text("aaa bbb ccc", 7), ["aaa bbb", "ccc"])

    def test_long_word_is_split(self):
        self.assertEqual(wrap_text("abcdefghij", 4), ["abcd", "efgh", "ij"])

    def test_long_word_in_the_middle(self):
        self.assertEqual(wrap_text("hi abcdefghij yo", 5), ["hi", "abcde", "fghij", "yo"])

    def test_remainder_of_long_word_can_be_joined(self):
        self.assertEqual(wrap_text("abcdefgh x", 5), ["abcde", "fgh x"])

    def test_paragraphs(self):
        self.assertEqual(wrap_text("one two\n\nthree four five", 9), ["one two", "", "three", "four five"])

    def test_blank_line_with_spaces_and_extra_newlines(self):
        self.assertEqual(wrap_text("a\n  \n\nb", 5), ["a", "", "b"])

    def test_single_newline_is_a_space(self):
        self.assertEqual(wrap_text("one\ntwo three", 20), ["one two three"])

    def test_whitespace_is_ignored(self):
        self.assertEqual(wrap_text("  hello   world  ", 20), ["hello world"])

    def test_empty(self):
        self.assertEqual(wrap_text("", 10), [])
        self.assertEqual(wrap_text("  \n  ", 10), [])
