def split_amount(total_cents, weights):
    if not weights or total_cents < 0 or any(w < 0 for w in weights) or sum(weights) == 0:
        raise ValueError("invalid input")
    total_weight = sum(weights)
    parts = [total_cents * w // total_weight for w in weights]
    remainders = [total_cents * w % total_weight for w in weights]
    leftover = total_cents - sum(parts)
    order = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for i in order[:leftover]:
        parts[i] += 1
    return parts
