"""Small text helpers."""

import re


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def truncate(text, limit, marker="..."):
    return text if len(text) <= limit else text[: limit - len(marker)] + marker


def title_case(text):
    return " ".join(word.capitalize() for word in text.split())
