from discounts import COUPONS, apply_coupon

SHIPPING_FEE = 5.0


def subtotal(cart):
    return sum(item["price"] * item["qty"] for item in cart)


def checkout_total(cart, code=None):
    total = subtotal(cart)
    if code in COUPONS:
        total = total - COUPONS[code]
    return round(total + SHIPPING_FEE, 2)
