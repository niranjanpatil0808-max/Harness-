"""Product catalog queries."""

from money import format_money
from textutil import slugify


class Product:
    def __init__(self, sku, name, price_cents, tags=()):
        self.sku = sku
        self.name = name
        self.price_cents = price_cents
        self.tags = tuple(tags)

    def slug(self):
        return slugify(self.name)

    def label(self):
        return f"{self.name} ({format_money(self.price_cents)})"


def search(products, text):
    """Products whose name or tags contain the text, case-insensitively, cheapest first."""
    needle = text.lower()
    hits = [p for p in products if needle in p.name.lower() or any(needle in tag.lower() for tag in p.tags)]
    return sorted(hits, key=lambda p: (p.price_cents, p.sku))


def by_tag(products):
    groups = {}
    for product in products:
        for tag in product.tags:
            groups.setdefault(tag, []).append(product.sku)
    return {tag: sorted(skus) for tag, skus in groups.items()}
