"""Shipping costs."""

from config import FREE_SHIPPING_MIN_CENTS, WEIGHT_BANDS


def shipping_cost(weight_grams, subtotal_cents):
    """Shipping in cents: free for big orders, otherwise by weight band (see config.WEIGHT_BANDS)."""
    if subtotal_cents >= FREE_SHIPPING_MIN_CENTS:
        return 0
    for max_grams, cents in WEIGHT_BANDS:
        if max_grams is None or weight_grams < max_grams:
            return cents
    return WEIGHT_BANDS[-1][1]


def is_free(subtotal_cents):
    return subtotal_cents >= FREE_SHIPPING_MIN_CENTS
