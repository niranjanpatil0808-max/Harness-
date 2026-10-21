TAX_RATE = 0.08


def apply_tax(amount):
    """Return amount with sales tax added."""
    return amount * (1 + TAX_RATE)
