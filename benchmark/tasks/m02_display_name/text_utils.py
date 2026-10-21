SMALL_WORDS = {"of", "and", "the", "van", "de", "von", "da"}


def title_case(text):
    """House style title case: small words stay lowercase unless first."""
    words = text.lower().split()
    out = []
    for i, word in enumerate(words):
        out.append(word if i > 0 and word in SMALL_WORDS else word.capitalize())
    return " ".join(out)
