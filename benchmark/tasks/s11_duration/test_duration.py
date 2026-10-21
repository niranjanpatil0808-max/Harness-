import unittest

from duration import parse_duration


class TestDuration(unittest.TestCase):
    def test_full(self):
        self.assertEqual(parse_duration("1h30m15s"), 5415)

    def test_minutes(self):
        self.assertEqual(parse_duration("45m"), 2700)

    def test_hours(self):
        self.assertEqual(parse_duration("2h"), 7200)

    def test_seconds(self):
        self.assertEqual(parse_duration("90s"), 90)
