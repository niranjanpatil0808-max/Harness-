import unittest
from datetime import datetime

from jobs import next_run

NOW = datetime(2026, 10, 21, 9, 0)


class TestNextRun(unittest.TestCase):
    def test_hourly(self):
        self.assertEqual(next_run({"frequency": "hourly"}, NOW), datetime(2026, 10, 21, 10, 0))

    def test_daily(self):
        self.assertEqual(next_run({"frequency": "daily"}, NOW), datetime(2026, 10, 22, 9, 0))
