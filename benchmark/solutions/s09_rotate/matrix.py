def rotate_clockwise(matrix):
    if not matrix:
        return []
    rows, cols = len(matrix), len(matrix[0])
    return [[matrix[r][c] for r in range(rows - 1, -1, -1)] for c in range(cols)]
