def moving_average(values, window):
    result = []
    for i in range(len(values) - window):
        chunk = values[i:i + window]
        result.append(sum(chunk) / window)
    return result
