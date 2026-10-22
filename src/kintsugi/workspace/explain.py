"""Turn what an AI provider answered into a sentence a person can act on."""
from __future__ import annotations

import re

_CODE = re.compile(r"Model API error (\d{3})")
_MESSAGE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _provider_words(text: str) -> str:
    """The provider's own explanation, if it gave one in the usual JSON shape (short, one line)."""
    m = _MESSAGE.search(text.replace("\\'", "'"))
    if not m:
        return ""
    words = " ".join(m.group(1).replace('\\"', '"').replace("\\n", " ").split())
    return words[:160]


def explain_model_error(err: BaseException | str) -> str:
    """A plain-language reason and what to do next. The provider's own words are added when it gave any."""
    text = str(err)
    m = _CODE.search(text)
    code = int(m.group(1)) if m else None
    theirs = _provider_words(text)
    tail = f" (the provider said: {theirs})" if theirs else ""
    if code in (401, 403):
        return "the AI provider did not accept your API key. It may be wrong, expired, or out of credit. Open Settings > Models, paste the key again and press Test." + tail
    if code == 404:
        return "the AI provider does not know this model name. Open Settings > Models, press Test and pick one of the models it lists." + tail
    if code == 429 or "asked to wait" in text:
        return ("you have used up the provider's rate or daily limit for now. Wait a little, or switch to another model or provider in Settings > Models." + tail)
    if code in (400, 413, 422):
        return ("the provider refused this request. Often the chat is too long for this model, or the model cannot do what was asked. "
                "Try a shorter chat, or another model in Settings > Models." + tail)
    if code is not None and code >= 500:
        return f"the AI provider had a problem on its side (error {code}). Try again in a minute." + tail
    if "unreachable" in text or "timed out" in text.lower():
        return "could not reach the AI provider. Check the connection, and that the address in Settings > Models is right."
    if "did not answer like an AI service" in text:
        return text[:200]  # already a plain sentence
    if "no AI model is set up" in text.lower() or "api key" in text.lower() and "set" in text.lower():
        return "no AI is connected yet. Open Settings > Models and add your API key."
    return text[:200]
