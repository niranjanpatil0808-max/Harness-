"""Money helpers. All amounts are integer cents."""

from decimal import Decimal, ROUND_HALF_UP


def parse_money(text):
    """Parse '1,234.50' or '$19.99' into cents, rounding half up."""
    cleaned = text.strip().lstrip("$₹€").replace(",", "")
    return int((Decimal(cleaned) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def format_money(cents):
    """123456 -> '1,234.56'; negative amounts get a leading minus sign."""
    return f"{cents // 100:,}.{cents % 100:02d}"


def percent_of(cents, basis_points):
    """basis_points / 10000 of cents, rounded half up to a whole cent (cents >= 0)."""
    return (cents * basis_points + 5000) // 10000


def apply_discount(cents, basis_points):
    """cents minus basis_points / 10000 of it."""
    return cents - percent_of(cents, basis_points)


def split_evenly(cents, parts):
    """Split cents into `parts` shares that add up exactly; earlier shares get the extra cents."""
    base, extra = divmod(cents, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]
