"""Export rows as CSV or JSON text."""

import json

from money import format_money


def to_csv(rows):
    """rows: list of (name, cents). Quotes names that contain commas or quotes."""
    lines = []
    for name, cents in rows:
        if any(ch in name for ch in ',"'):
            name = '"' + name.replace('"', '""') + '"'
        lines.append(f"{name},{format_money(cents)}")
    return "\n".join(lines)


def to_json(rows):
    return json.dumps([{"name": name, "cents": cents} for name, cents in rows], sort_keys=True)
