"""Date helpers."""

from datetime import timedelta


def days_between(a, b):
    return abs((b - a).days)


def add_days(day, n):
    return day + timedelta(days=n)


def is_weekend(day):
    return day.weekday() >= 5


def quarter_of(day):
    return (day.month - 1) // 3 + 1
