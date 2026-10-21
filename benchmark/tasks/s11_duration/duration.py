import re

UNITS = {"h": 3600, "m": 3600, "s": 1}


def parse_duration(text):
    total = 0
    for amount, unit in re.findall(r"(\d+)([hms])", text):
        total += int(amount) * UNITS[unit]
    return total
