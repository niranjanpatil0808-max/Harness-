import re

UNITS = {"h": 3600, "m": 60, "s": 1}


def parse_duration(text):
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * UNITS[unit]
    return total
