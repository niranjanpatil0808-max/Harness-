import unittest
from datetime import date

from bizdays import add_business_days

FRI = date(2026, 10, 23)
SAT = date(2026, 10, 24)
MON = date(2026, 10, 26)


class TestAddBusinessDays(unittest.TestCase):
    def test_over_the_weekend(self):
        self.assertEqual(add_business_days(FRI, 1, set()), MON)
        self.assertEqual(add_business_days(date(2026, 10, 21), 3, set()), MON)

    def test_several_weeks(self):
        self.assertEqual(add_business_days(date(2026, 10, 21), 10, set()), date(2026, 11, 4))

    def test_backwards(self):
        self.assertEqual(add_business_days(MON, -1, set()), FRI)

    def test_start_on_a_weekend(self):
        self.assertEqual(add_business_days(SAT, 1, set()), MON)
        self.assertEqual(add_business_days(SAT, -1, set()), FRI)

    def test_zero_returns_start(self):
        self.assertEqual(add_business_days(SAT, 0, set()), SAT)
        self.assertEqual(add_business_days(MON, 0, {MON}), MON)

    def test_holiday_is_skipped(self):
        self.assertEqual(add_business_days(FRI, 1, {MON}), date(2026, 10, 27))

    def test_holiday_backwards(self):
        self.assertEqual(add_business_days(date(2026, 10, 27), -2, {MON}), date(2026, 10, 22))

    def test_holiday_on_a_weekend_changes_nothing(self):
        self.assertEqual(add_business_days(FRI, 1, {SAT}), MON)
