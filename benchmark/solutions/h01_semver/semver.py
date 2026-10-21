def _parse(version):
    version = version.split("+", 1)[0]
    core, _, pre = version.partition("-")
    return [int(part) for part in core.split(".")], (pre.split(".") if pre else [])


def _compare_identifier(x, y):
    x_numeric, y_numeric = x.isdigit(), y.isdigit()
    if x_numeric and y_numeric:
        return (int(x) > int(y)) - (int(x) < int(y))
    if x_numeric:
        return -1
    if y_numeric:
        return 1
    return (x > y) - (x < y)


def compare_versions(a, b):
    core_a, pre_a = _parse(a)
    core_b, pre_b = _parse(b)
    if core_a != core_b:
        return -1 if core_a < core_b else 1
    if not pre_a and not pre_b:
        return 0
    if not pre_a:
        return 1
    if not pre_b:
        return -1
    for x, y in zip(pre_a, pre_b):
        result = _compare_identifier(x, y)
        if result:
            return result
    return (len(pre_a) > len(pre_b)) - (len(pre_a) < len(pre_b))
