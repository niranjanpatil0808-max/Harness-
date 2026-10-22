from units import MM_PER_CM


def total_length_mm(segments):
    return sum(segments)


def total_length_cm(segments):
    return total_length_mm(segments) / MM_PER_CM
