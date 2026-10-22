"""Order pricing."""

from config import BULK_BREAKS
from customers import loyalty_discount_bps
from money import apply_discount
from taxes import tax_for


def line_total(unit_cents, qty):
    return unit_cents * qty


def bulk_discount_bps(qty):
    discount = 0
    for minimum, bps in BULK_BREAKS:
        if qty >= minimum:
            discount = bps
    return discount


def order_summary(lines, region, lifetime_spend_cents=0):
    """lines: list of (unit_cents, qty). Returns subtotal, discount, tax and total, all in cents.

    The loyalty discount is taken off the subtotal first; tax is charged on the discounted amount.
    """
    subtotal = sum(line_total(unit, qty) for unit, qty in lines)
    discounted = apply_discount(subtotal, loyalty_discount_bps(lifetime_spend_cents))
    tax = tax_for(discounted, region)
    return {"subtotal": subtotal, "discount": subtotal - discounted, "tax": tax, "total": discounted + tax}
