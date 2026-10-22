"""Customer notification texts."""

from customers import normalize_name, valid_email
from textutil import truncate


def order_confirmation(name, order_id, grand_total_text):
    return f"Hello {normalize_name(name)}, order {order_id} is confirmed. Total: {grand_total_text}."


def sms_text(message, limit=160):
    return truncate(message, limit)


def can_email(address):
    return valid_email(address)
