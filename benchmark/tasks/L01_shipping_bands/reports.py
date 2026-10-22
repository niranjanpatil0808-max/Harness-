"""Sales reports."""

from money import format_money


def sales_table(rows):
    """rows: list of (name, cents). Returns aligned text lines."""
    if not rows:
        return []
    width = max(len(name) for name, _ in rows)
    return [f"{name.ljust(width)}  {format_money(cents).rjust(12)}" for name, cents in rows]


def top_sellers(rows, count=3):
    return [name for name, _ in sorted(rows, key=lambda row: (-row[1], row[0]))[:count]]


def total_row(rows):
    return ("TOTAL", sum(cents for _, cents in rows))
