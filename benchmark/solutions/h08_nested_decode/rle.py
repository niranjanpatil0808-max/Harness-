def decode(s):
    stack = [[]]
    counts = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch in "0123456789":
            j = i
            while j < n and s[j] in "0123456789":
                j += 1
            count = int(s[i:j])
            if j >= n:
                raise ValueError("number at the end")
            nxt = s[j]
            if nxt == "(":
                stack.append([])
                counts.append(count)
            elif nxt.isascii() and nxt.isalpha():
                stack[-1].append(nxt * count)
            else:
                raise ValueError("number must be followed by a letter or '('")
            i = j + 1
        elif ch == ")":
            if not counts:
                raise ValueError("unbalanced ')'")
            inner = "".join(stack.pop())
            stack[-1].append(inner * counts.pop())
            i += 1
        elif ch.isascii() and ch.isalpha():
            stack[-1].append(ch)
            i += 1
        else:
            raise ValueError(f"unexpected character {ch!r}")
    if counts:
        raise ValueError("unbalanced '('")
    return "".join(stack[0])
