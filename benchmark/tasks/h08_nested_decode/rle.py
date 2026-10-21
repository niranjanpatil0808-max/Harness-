import re


def decode(s):
    s = re.sub(r"(\d+)\(([a-zA-Z]*)\)", lambda m: m.group(2) * int(m.group(1)), s)
    return re.sub(r"(\d+)([a-zA-Z])", lambda m: m.group(2) * int(m.group(1)), s)
