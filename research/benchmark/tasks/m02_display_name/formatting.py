"""Text formatting for reports and emails."""


def pad_table(rows, sep=" | "):
    if not rows:
        return ""
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = [str(cell).ljust(width) for cell, width in zip(row, widths)]
        lines.append(sep.join(cells).rstrip())
    return "\n".join(lines)


def money(amount, currency="$"):
    sign = "-" if amount < 0 else ""
    return f"{sign}{currency}{abs(amount):,.2f}"


def plural(count, word, suffix="s"):
    return f"{count} {word}{'' if count == 1 else suffix}"


def truncate(text, limit=40, marker="..."):
    if len(text) <= limit:
        return text
    return text[: limit - len(marker)] + marker


def bullet_list(items, bullet="-"):
    return "\n".join(f"{bullet} {item}" for item in items)
