"""Model providers: bring your own key, any model.

A *profile* is a saved connection (which service, which address, which model). The key is kept in the keychain, is
write-only, and is sent only to that profile's own address. Three wire formats cover nearly everything:

  openai     the OpenAI-style chat API that OpenAI, DeepSeek, Groq, Together, Fireworks, OpenRouter, Gemini's
             compatibility endpoint, Ollama and LM Studio all speak
  anthropic  Claude's own API
  gemini     Google's own Gemini API

The idea of keeping providers behind one small adapter seam is taken from DeepSeek Harness (MIT), which registers
model adapters on a shared context; the code here is written from scratch for this project.
"""

from __future__ import annotations

import ipaddress
import json
import re
import urllib.parse
import urllib.request

from kintsugi.model import USER_AGENT, Model, OpenAIAdapter, request_json

KINDS = ("openai", "anthropic", "gemini")
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,23}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}

# Suggestions only: the Test button lists what the key can really use, and the owner picks.
PRESETS = {
    "openai": {"label": "OpenAI", "kind": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "signup": "https://platform.openai.com/api-keys"},
    "anthropic": {"label": "Anthropic (Claude)", "kind": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-haiku-5-5", "signup": "https://console.anthropic.com/settings/keys"},
    "gemini": {"label": "Google Gemini", "kind": "gemini", "base_url": "https://generativelanguage.googleapis.com", "model": "gemini-2.5-flash", "signup": "https://aistudio.google.com/apikey"},
    "deepseek": {"label": "DeepSeek", "kind": "openai", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "signup": "https://platform.deepseek.com/api_keys"},
    "groq": {"label": "Groq (free tier)", "kind": "openai", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "signup": "https://console.groq.com/keys"},
    "openrouter": {"label": "OpenRouter (many models)", "kind": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "meta-llama/llama-3.3-70b-instruct", "signup": "https://openrouter.ai/keys"},
    "together": {"label": "Together AI", "kind": "openai", "base_url": "https://api.together.xyz/v1", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo", "signup": "https://api.together.ai/settings/api-keys"},
    "fireworks": {"label": "Fireworks AI", "kind": "openai", "base_url": "https://api.fireworks.ai/inference/v1", "model": "", "signup": "https://fireworks.ai/account/api-keys"},
    "ollama": {"label": "Ollama on this computer (no key)", "kind": "openai", "base_url": "http://localhost:11434/v1", "model": "", "signup": "https://ollama.com", "keyless": True},
    "custom": {"label": "Another OpenAI-compatible service", "kind": "openai", "base_url": "", "model": "", "signup": ""},
}


class ProviderError(RuntimeError):
    """A problem with a provider setting the owner can fix (shown as-is; never contains a key)."""


def clean_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parts = urllib.parse.urlsplit(url)
    if not url or parts.scheme not in ("https", "http") or not parts.hostname:
        raise ProviderError("the address must start with https:// (for example https://api.openai.com/v1)")
    if parts.username or parts.password or parts.query or parts.fragment or re.search(r"\s", url):
        raise ProviderError("the address must be a plain URL with no password, query or spaces")
    if parts.scheme == "http" and parts.hostname not in LOCAL_HOSTS:
        raise ProviderError("only https:// addresses are allowed, except for a model running on this computer (localhost)")
    try:
        ip = ipaddress.ip_address(parts.hostname)
        if parts.hostname not in LOCAL_HOSTS and not ip.is_global:
            raise ProviderError("that address is a private or internal network address, not a model service")
    except ValueError:
        pass  # a normal host name
    return url


def clean_model(model: str) -> str:
    model = (model or "").strip()
    if model and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,100}", model):
        raise ProviderError("model names use letters, digits and . _ : / @ + -")
    return model


class AnthropicAdapter(Model):
    VERSION = "2023-06-01"

    def __init__(self, base_url: str, model: str, api_key: str, max_tokens: int = 2048, temperature: float = 0.0,
                 timeout: float = 90.0, max_retries: int = 4) -> None:
        super().__init__()
        self.base_url, self.name, self.api_key = base_url.rstrip("/"), model, api_key
        self.max_tokens, self.temperature, self.timeout, self.max_retries = max_tokens, temperature, timeout, max_retries

    def _headers(self) -> dict:
        return {"x-api-key": self.api_key, "anthropic-version": self.VERSION, "content-type": "application/json", "User-Agent": USER_AGENT}

    def list_models(self) -> list[str]:
        request = urllib.request.Request(f"{self.base_url}/v1/models?limit=100", headers=self._headers())
        return sorted(item["id"] for item in request_json(request, 20.0, 0).get("data", []))

    def complete(self, messages: list[dict]) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "assistant" if m["role"] == "assistant" else "user"
            if turns and turns[-1]["role"] == role:  # the API wants alternating roles
                turns[-1]["content"] += "\n\n" + m["content"]
            else:
                turns.append({"role": role, "content": m["content"]})
        if not turns or turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "(start)"})
        body = {"model": self.name, "max_tokens": self.max_tokens, "temperature": self.temperature, "messages": turns}
        if system:
            body["system"] = system
        request = urllib.request.Request(f"{self.base_url}/v1/messages", data=json.dumps(body).encode(), headers=self._headers())
        data = request_json(request, self.timeout, self.max_retries)
        self.usage.calls += 1
        usage = data.get("usage") or {}
        self.usage.prompt_tokens += usage.get("input_tokens", 0)
        self.usage.completion_tokens += usage.get("output_tokens", 0)
        return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()


class GeminiAdapter(Model):
    def __init__(self, base_url: str, model: str, api_key: str, max_tokens: int = 2048, temperature: float = 0.0,
                 timeout: float = 90.0, max_retries: int = 4) -> None:
        super().__init__()
        self.base_url, self.name, self.api_key = base_url.rstrip("/"), model, api_key
        self.max_tokens, self.temperature, self.timeout, self.max_retries = max_tokens, temperature, timeout, max_retries

    def _headers(self) -> dict:  # the key goes in a header, never in the address, so it cannot end up in a log line
        return {"x-goog-api-key": self.api_key, "content-type": "application/json", "User-Agent": USER_AGENT}

    def list_models(self) -> list[str]:
        request = urllib.request.Request(f"{self.base_url}/v1beta/models?pageSize=100", headers=self._headers())
        data = request_json(request, 20.0, 0)
        return sorted(m["name"].split("/", 1)[-1] for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", []))

    def complete(self, messages: list[dict]) -> str:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                continue
            role = "model" if m["role"] == "assistant" else "user"
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"][0]["text"] += "\n\n" + m["content"]
            else:
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        body = {"contents": contents or [{"role": "user", "parts": [{"text": "(start)"}]}],
                "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_tokens}}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.base_url}/v1beta/models/{urllib.parse.quote(self.name, safe='')}:generateContent"
        data = request_json(urllib.request.Request(url, data=json.dumps(body).encode(), headers=self._headers()), self.timeout, self.max_retries)
        self.usage.calls += 1
        usage = data.get("usageMetadata") or {}
        self.usage.prompt_tokens += usage.get("promptTokenCount", 0)
        self.usage.completion_tokens += usage.get("candidatesTokenCount", 0)
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
        return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def build(profile: dict, key: str | None, model: str | None = None) -> Model:
    """A ready model from a saved profile (kind, base_url, model), its key, and an optional model override."""
    chosen = model or profile.get("model") or ""
    if not chosen:
        raise ProviderError("no model is chosen yet: pick one in Settings > Models")
    kind, base = profile["kind"], profile["base_url"]
    if kind == "anthropic":
        return AnthropicAdapter(base, chosen, key or "")
    if kind == "gemini":
        return GeminiAdapter(base, chosen, key or "")
    return OpenAIAdapter(base_url=base, model=chosen, api_key=key or "none")  # keyless local servers ignore the header
