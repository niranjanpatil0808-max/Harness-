# Coupon code -> fraction of the subtotal taken off (0.10 means 10% off).
COUPONS = {
    "WELCOME10": 0.10,
    "FESTIVE25": 0.25,
}


def apply_coupon(amount, code):
    """Return amount after the coupon's percentage discount; unknown codes change nothing."""
    return amount * (1 - COUPONS.get(code, 0.0))
