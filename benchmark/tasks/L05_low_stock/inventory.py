"""Stock keeping."""

from config import LOW_STOCK_THRESHOLD, MAX_QTY_PER_LINE


class Stock:
    def __init__(self):
        self._on_hand = {}
        self._reserved = {}

    def add(self, sku, qty):
        self._on_hand[sku] = self._on_hand.get(sku, 0) + qty

    def available(self, sku):
        """Units that can still be reserved: on hand minus reserved."""
        return self._on_hand.get(sku, 0) - self._reserved.get(sku, 0)

    def reserve(self, sku, qty):
        if qty < 1 or qty > MAX_QTY_PER_LINE:
            raise ValueError("bad quantity")
        if qty > self.available(sku):
            raise ValueError("not enough stock")
        self._reserved[sku] = self._reserved.get(sku, 0) + qty

    def release(self, sku, qty):
        self._reserved[sku] = max(0, self._reserved.get(sku, 0) - qty)

    def low_stock(self):
        """SKUs whose available stock is at or below the low-stock threshold, sorted by name."""
        return sorted(sku for sku in self._on_hand if self._on_hand[sku] < LOW_STOCK_THRESHOLD)
