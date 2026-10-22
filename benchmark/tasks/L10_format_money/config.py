"""Shop-wide constants. Money is always an integer number of cents."""

# Tax rate per region in basis points (1/100 of a percent): 1800 means 18%.
TAX_RATES_BPS = {"IN": 1800, "US": 700, "EU": 2000}
DEFAULT_REGION = "IN"  # rate used for any region that is not listed above

# Shipping bands: (max_grams, cents). max_grams is an INCLUSIVE upper bound;
# the last band has no limit (None).
WEIGHT_BANDS = [(500, 4000), (2000, 8000), (5000, 15000), (None, 30000)]
FREE_SHIPPING_MIN_CENTS = 500000  # orders with a subtotal of at least this ship free

# Loyalty tiers: (minimum lifetime spend in cents, discount in basis points), ascending.
# A customer gets the discount of the highest tier whose minimum they have reached (>=).
LOYALTY_TIERS = [(0, 0), (10000, 500), (50000, 1000), (200000, 1500)]

LOW_STOCK_THRESHOLD = 5  # a product is "low" when its available stock is AT OR BELOW this
MAX_QTY_PER_LINE = 99
BULK_BREAKS = [(10, 500), (50, 1000), (100, 1500)]  # (min quantity, discount bps)
