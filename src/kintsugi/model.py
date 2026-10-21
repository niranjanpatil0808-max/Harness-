"""Model adapters.

`OpenAIAdapter` talks to any OpenAI-compatible chat endpoint (Groq, Together,
Fireworks, Meta Llama API, a local Ollama server...). `MockModel` replays
scripted answers so the whole pipeline can be tested offline.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.1-8b-instant"


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


class OpenAIAdapter(Model):
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 6,
    ) -> None:
        super().__init__()
        self.base_url = (base_url or os.environ.get("KINTSUGI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.name = model or os.environ.get("KINTSUGI_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("KINTSUGI_API_KEY") or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise RuntimeError("No API key: set KINTSUGI_API_KEY (or GROQ_API_KEY).")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(self, messages: list[dict]) -> str:
        body = json.dumps({
            "model": self.name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as err:
                # Rate limits and server hiccups are retried; anything else is a real error.
                if err.code not in (429, 500, 502, 503, 504) or attempt == self.max_retries:
                    raise RuntimeError(f"Model API error {err.code}: {err.read()[:500]!r}") from err
                retry_after = err.headers.get("retry-after")
                time.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
            except (urllib.error.URLError, TimeoutError):
                if attempt == self.max_retries:
                    raise
                time.sleep(delay)
                delay *= 2
        self.usage.calls += 1
        usage = data.get("usage") or {}
        self.usage.prompt_tokens += usage.get("prompt_tokens", 0)
        self.usage.completion_tokens += usage.get("completion_tokens", 0)
        return data["choices"][0]["message"]["content"] or ""


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
