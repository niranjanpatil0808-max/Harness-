from datetime import timedelta


def add_business_days(start, n, holidays):
    day = start
    while n > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day
