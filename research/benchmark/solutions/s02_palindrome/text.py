def is_palindrome(text):
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum())
    return cleaned == cleaned[::-1]
