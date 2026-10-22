"""Customer rules."""

from config import LOYALTY_TIERS


def loyalty_discount_bps(lifetime_spend_cents):
    """Discount (basis points) of the highest loyalty tier the customer has reached."""
    discount = 0
    for minimum, bps in LOYALTY_TIERS:
        if lifetime_spend_cents >= minimum:
            discount = bps
    return discount


def valid_email(text):
    local, _, domain = text.partition("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".") and " " not in text


def normalize_name(text):
    return " ".join(part.capitalize() for part in text.split())


def valid_phone(text):
    digits = [ch for ch in text if ch.isdigit()]
    return 10 <= len(digits) <= 13
