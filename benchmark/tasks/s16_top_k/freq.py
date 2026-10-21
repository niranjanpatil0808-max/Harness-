from collections import Counter


def top_k(words, k):
    counts = Counter(words)
    ranked = sorted(counts.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)
    return [word for word, _ in ranked[:k]]
