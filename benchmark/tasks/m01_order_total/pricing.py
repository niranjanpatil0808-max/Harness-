from tax import apply_tax, TAX_RATE


def subtotal(items):
    return sum(price * qty for price, qty in items)


def order_total(items):
    return round(subtotal(items) * TAX_RATE, 2)
