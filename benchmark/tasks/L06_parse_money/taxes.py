"""Sales tax."""

from config import DEFAULT_REGION, TAX_RATES_BPS
from money import percent_of


def tax_rate_bps(region):
    """Tax rate of a region in basis points; unknown regions use the default region's rate."""
    return TAX_RATES_BPS.get(region, TAX_RATES_BPS[DEFAULT_REGION])


def tax_for(cents, region):
    """Tax on an amount of cents, rounded half up to a whole cent."""
    return percent_of(cents, tax_rate_bps(region))


def price_with_tax(cents, region):
    return cents + tax_for(cents, region)
