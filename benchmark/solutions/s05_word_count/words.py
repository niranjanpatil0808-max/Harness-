import string


def word_count(text):
    counts = {}
    for word in text.lower().split():
        word = word.strip(string.punctuation)
        if word:
            counts[word] = counts.get(word, 0) + 1
    return counts
