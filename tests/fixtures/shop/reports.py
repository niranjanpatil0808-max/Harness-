import pricing


def monthly_report(orders):
    lines = []
    for name, total in orders:
        lines.append(f"{name}: {total:.2f}")
    return "\n".join(lines)


def format_header(title):
    return title.upper().center(40, "=")
