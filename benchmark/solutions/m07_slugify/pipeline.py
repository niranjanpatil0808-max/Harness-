from tokenizer import tokenize


def slugify(title):
    return "-".join(tokenize(title, keep_numbers=True))
