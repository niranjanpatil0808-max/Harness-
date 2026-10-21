import re


def tokenize(text, keep_numbers=False):
    """Split text into lowercase word tokens.

    Numbers are dropped unless keep_numbers=True.
    """
    pattern = r"[a-z0-9]+" if keep_numbers else r"[a-z]+"
    return re.findall(pattern, text.lower())
