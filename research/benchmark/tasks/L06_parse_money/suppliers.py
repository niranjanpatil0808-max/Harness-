"""Supplier lead times and reorder suggestions."""

from config import LOW_STOCK_THRESHOLD

LEAD_TIMES_DAYS = {"acme": 7, "globex": 14, "initech": 3}


def lead_time(supplier):
    return LEAD_TIMES_DAYS.get(supplier, 10)


def reorder_quantity(sold_per_week, supplier, safety_weeks=1):
    """Units to order so stock lasts through the lead time plus a safety margin."""
    weeks = lead_time(supplier) / 7 + safety_weeks
    return max(LOW_STOCK_THRESHOLD, round(sold_per_week * weeks))


def slowest_supplier(suppliers):
    return max(suppliers, key=lead_time)
