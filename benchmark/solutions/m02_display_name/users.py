from text_utils import title_case


def full_name(user):
    return " ".join(part for part in (user.get("first"), user.get("middle"), user.get("last")) if part)


def display_name(user):
    return title_case(full_name(user))
