def caesar(text, shift):
    out = []
    for ch in text:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            out.append(chr(base + (ord(ch) - base + shift) % 26))
        else:
            out.append(ch)
    return "".join(out)
