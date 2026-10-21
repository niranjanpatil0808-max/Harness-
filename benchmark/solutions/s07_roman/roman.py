VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def roman_to_int(s):
    total = 0
    for i, ch in enumerate(s):
        value = VALUES[ch]
        if i + 1 < len(s) and VALUES[s[i + 1]] > value:
            total -= value
        else:
            total += value
    return total
