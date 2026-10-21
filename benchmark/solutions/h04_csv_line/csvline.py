def parse_csv_line(line):
    fields, i, n = [], 0, len(line)
    while True:
        if i < n and line[i] == '"':
            i += 1
            chars = []
            while True:
                if i >= n:
                    raise ValueError("unterminated quoted field")
                ch = line[i]
                if ch == '"':
                    if i + 1 < n and line[i + 1] == '"':
                        chars.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                chars.append(ch)
                i += 1
            if i < n and line[i] != ",":
                raise ValueError("text after closing quote")
            fields.append("".join(chars))
        else:
            end = line.find(",", i)
            if end == -1:
                end = n
            fields.append(line[i:end])
            i = end
        if i >= n:
            break
        i += 1  # skip the comma
        if i >= n:
            fields.append("")
            break
    return fields
