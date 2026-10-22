import re


def _wrap_paragraph(words, width):
    lines, current = [], ""
    for word in words:
        while len(word) > width:
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:width])
            word = word[width:]
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrap_text(text, width):
    if not text.strip():
        return []
    lines = []
    for index, paragraph in enumerate(re.split(r"\n\s*\n", text.strip())):
        if index:
            lines.append("")
        lines.extend(_wrap_paragraph(paragraph.split(), width))
    return lines
