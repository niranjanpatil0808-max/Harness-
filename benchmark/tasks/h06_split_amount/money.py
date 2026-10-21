def split_amount(total_cents, weights):
    total_weight = sum(weights)
    parts = [round(total_cents * weight / total_weight) for weight in weights]
    parts[-1] += total_cents - sum(parts)
    return parts
