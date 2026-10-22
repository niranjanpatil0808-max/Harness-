"""Model adapters.

`OpenAIAdapter` talks to any OpenAI-compatible chat endpoint (Groq, Together,
Fireworks, Meta Llama API, a local Ollama server...). `MockModel` replays
scripted answers so the whole pipeline can be tested offline.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"
THINK_RE = re.compile(r"<think>.*?</think>", re.S)
MAX_WAIT = 300.0  # longest rate-limit wait (seconds) we will sit through
USER_AGENT = "kintsugi/0.1 (+https://github.com/niranjanpatil0808-max/KINTSUGI)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the default handler would copy an API key to wherever the answer points (even plain http)."""

    def redirect_request(self, *args, **kwargs):
        return None


urllib.request.install_opener(urllib.request.build_opener(_NoRedirect))  # covers every urlopen in the process: providers, search, backup, push


class ModelRequestError(RuntimeError):
    """The API rejected this particular request as invalid or too long for the model. Counts against the model."""


class ModelInfraError(RuntimeError):
    """No answer for reasons that say nothing about the model: rate limit, request over the
    per-minute token limit, timeout, server error. Never counted as a failed task."""


class QuotaExhausted(RuntimeError):
    """A daily quota is used up: stop the whole run (finished tasks are already saved)."""


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class Model:
    """Interface: take a list of chat messages, return the reply text."""

    name = "model"

    def __init__(self) -> None:
        self.usage = Usage()

    def complete(self, messages: list[dict]) -> str:
        raise NotImplementedError


def request_json(request: urllib.request.Request, timeout: float, max_retries: int) -> dict:
    """Send a prepared request and return the parsed JSON reply, with the retry and error rules every adapter shares:
    400/422 -> ModelRequestError (the request is bad), rate limits and server errors -> wait and retry, then
    ModelInfraError, a daily quota -> QuotaExhausted, anything else (bad key, unknown model) -> RuntimeError."""
    delay = 2.0
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                try:
                    return json.load(response)
                except ValueError:  # an HTML page or empty answer: the address is not an AI API
                    raise RuntimeError("that address did not answer like an AI service (does it end in /v1?)") from None
        except urllib.error.HTTPError as err:
            body_text = err.read()[:500].decode("utf-8", "replace")
            detail = f"Model API error {err.code}: {body_text!r}"
            per_minute = "per minute" in body_text.lower()
            if err.code in (400, 422) or (err.code == 413 and not per_minute):
                raise ModelRequestError(detail) from err
            if err.code == 413:  # request + max_tokens larger than the per-minute token limit
                raise ModelInfraError(f"{detail} (lower KINTSUGI_MAX_TOKENS)") from err
            if err.code not in (429, 500, 502, 503, 504, 529):
                raise RuntimeError(detail) from err  # bad key, unknown model...: a setup problem
            retry_after = err.headers.get("retry-after")
            try:
                wait = float(retry_after) if retry_after else delay
            except ValueError:  # an HTTP-date instead of seconds
                wait = delay
            if wait > MAX_WAIT:  # a daily quota, not a short rate limit
                raise QuotaExhausted(f"{detail} (asked to wait {wait:.0f}s)") from err
            if attempt == max_retries:
                raise ModelInfraError(detail) from err
            time.sleep(wait)
            delay *= 2
        except (urllib.error.URLError, TimeoutError) as err:
            if attempt == max_retries:
                raise ModelInfraError(f"Model API unreachable: {err}") from err
            time.sleep(delay)
            delay *= 2
    raise ModelInfraError("Model API gave no answer")  # unreachable; keeps the type checker happy


class OpenAIAdapter(Model):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float | None = None,
        extra: dict | None = None,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        max_retries: int = 6,
    ) -> None:
        super().__init__()
        self.base_url = (base_url or os.environ.get("KINTSUGI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.name = model or os.environ.get("KINTSUGI_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("KINTSUGI_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("No API key: set KINTSUGI_API_KEY (or GROQ_API_KEY).")
        # Temperature and extra request fields (e.g. {"reasoning_effort": "low"}) can come from the environment.
        env_temperature = os.environ.get("KINTSUGI_TEMPERATURE")
        self.temperature = temperature if temperature is not None else float(env_temperature or 0.0)
        self.extra = extra if extra is not None else json.loads(os.environ.get("KINTSUGI_EXTRA") or "{}")
        # Thinking models spend tokens reasoning before they answer, so this is configurable.
        self.max_tokens = max_tokens or int(os.environ.get("KINTSUGI_MAX_TOKENS", "2048"))
        self.timeout = timeout
        self.max_retries = max_retries

    def list_models(self) -> list[str]:
        """Model ids this key can use (GET {base_url}/models)."""
        request = urllib.request.Request(f"{self.base_url}/models", headers={
            "Authorization": f"Bearer {self.api_key}", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return sorted(item["id"] for item in json.load(response)["data"])

    def complete(self, messages: list[dict]) -> str:
        body = json.dumps({
            "model": self.name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **self.extra,
        }).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                # Some providers' firewalls (Cloudflare error 1010) reject Python's default User-Agent.
                "User-Agent": USER_AGENT,
            },
        )
        data = request_json(request, self.timeout, self.max_retries)
        self.usage.calls += 1
        usage = data.get("usage") or {}
        self.usage.prompt_tokens += usage.get("prompt_tokens", 0)
        self.usage.completion_tokens += usage.get("completion_tokens", 0)
        text = data["choices"][0]["message"].get("content") or ""
        return THINK_RE.sub("", text).strip()  # drop <think> blocks some models put inline


@dataclass
class MockModel(Model):
    """Replays scripted replies.

    `script` is either a list of replies (returned in order, the last one
    repeated) or a function `messages -> reply` for tests that need to react
    to the prompt.
    """

    script: list[str] | Callable[[list[dict]], str] = field(default_factory=list)
    name: str = "mock"

    def __post_init__(self) -> None:
        super().__init__()
        self.prompts: list[list[dict]] = []

    def complete(self, messages: list[dict]) -> str:
        self.prompts.append(messages)
        self.usage.calls += 1
        if callable(self.script):
            return self.script(messages)
        if not self.script:
            return ""
        index = min(len(self.prompts) - 1, len(self.script) - 1)
        return self.script[index]
