from datetime import timedelta


def add_business_days(start, n, holidays):
    step = 1 if n > 0 else -1
    day, remaining = start, abs(n)
    while remaining:
        day += timedelta(days=step)
        if day.weekday() < 5 and day not in holidays:
            remaining -= 1
    return day
