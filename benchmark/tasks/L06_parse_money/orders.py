"""Checkout."""

from pricing import order_summary
from shipping import shipping_cost


def checkout(lines, weight_grams, region, lifetime_spend_cents=0):
    """Price an order and add shipping. Free shipping depends on the SUBTOTAL before any discount."""
    summary = order_summary(lines, region, lifetime_spend_cents)
    ship = shipping_cost(weight_grams, summary["subtotal"])
    return {**summary, "shipping": ship, "grand_total": summary["total"] + ship}
