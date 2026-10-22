def caesar(text, shift):
    out = []
    for ch in text:
        if ch.isalpha():
            out.append(chr(ord(ch) + shift))
        else:
            out.append(ch)
    return "".join(out)
