import unittest

from csvline import parse_csv_line


class TestParseCsvLine(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(parse_csv_line("a,b,c"), ["a", "b", "c"])

    def test_empty_fields(self):
        self.assertEqual(parse_csv_line("a,,c"), ["a", "", "c"])
        self.assertEqual(parse_csv_line("a,b,"), ["a", "b", ""])
        self.assertEqual(parse_csv_line(",,"), ["", "", ""])

    def test_empty_line(self):
        self.assertEqual(parse_csv_line(""), [""])

    def test_comma_inside_quotes(self):
        self.assertEqual(parse_csv_line('"a,b",c'), ["a,b", "c"])

    def test_doubled_quote(self):
        self.assertEqual(parse_csv_line('"say ""hi""",x'), ['say "hi"', "x"])

    def test_empty_quoted_field(self):
        self.assertEqual(parse_csv_line('""'), [""])
        self.assertEqual(parse_csv_line('"",x'), ["", "x"])

    def test_spaces_are_kept(self):
        self.assertEqual(parse_csv_line(" a , b "), [" a ", " b "])
        self.assertEqual(parse_csv_line('"  x  ",y'), ["  x  ", "y"])

    def test_quote_in_the_middle_is_literal(self):
        self.assertEqual(parse_csv_line('a"b,c'), ['a"b', "c"])

    def test_unterminated_quote(self):
        with self.assertRaises(ValueError):
            parse_csv_line('"abc')
        with self.assertRaises(ValueError):
            parse_csv_line('a,"b')

    def test_text_after_closing_quote(self):
        with self.assertRaises(ValueError):
            parse_csv_line('"a"b,c')
