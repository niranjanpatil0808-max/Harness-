from tokenizer import tokenize


def slugify(title):
    return "-".join(tokenize(title))
