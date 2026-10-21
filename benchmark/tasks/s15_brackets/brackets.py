PAIRS = {")": "(", "]": "[", "}": "{"}


def is_balanced(text):
    stack = []
    for ch in text:
        if ch in "([{":
            stack.append(ch)
        elif ch in PAIRS:
            if not stack:
                return False
            stack.pop()
    return True
