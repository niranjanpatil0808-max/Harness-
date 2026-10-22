"""The workspace: agents, rooms, direct messages, approvals and jobs, and the routing between them.

People and agents talk in rooms. A message wakes an agent when it is addressed to it: an @mention in a
room, or any message in a direct-message room. Agent replies carry a "hop" count, and a thread of
agents answering agents stops after MAX_HOPS, so two agents can never chat forever.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from kintsugi.memory import tokens
from kintsugi.model import Model, ModelInfraError, ModelRequestError, OpenAIAdapter, QuotaExhausted

from . import perms, providers
from .db import Database
from .keychain import Keychain

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HUMAN_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,40}$")
MENTION_RE = re.compile(r"(?<![\w@])@([a-z][a-z0-9_-]*)")
MAX_HOPS = 4  # agent-to-agent replies in a row before the thread goes quiet
MAX_RUNS_PER_MINUTE = 20  # per agent
MAX_MESSAGE_CHARS = 4000
MAX_AGENTS = 50
MAX_ROOMS = 200
DEFAULT_DAILY_CALLS = 500  # model calls per day for the whole workspace; KINTSUGI_DAILY_CALLS=0 turns the cap off


class WorkspaceError(ValueError):
    """A request the workspace refuses (unknown agent, bad name, not a member...)."""


TONES = {
    "regular": "Be clear, friendly and neutral.",
    "fun": ("Be witty and direct, with a light sense of humour, like a sharp friend. Keep it short; a quick joke or playful "
            "aside is welcome when it fits. Never insult or mock anyone, never use profanity, and drop the jokes for serious "
            "topics (money, health, safety, legal) and for anything the user seems stressed about."),
    "concise": "Be extremely brief: answer in as few words as you can while staying correct.",
}
TONE_LABELS = {"fun": "Fun: witty and direct", "regular": "Regular: clear and neutral", "concise": "Brief: as few words as possible", "custom": "Custom"}
DEFAULT_TONE = "fun"
# A custom style is the user's own words, but it must not be a way to loosen the rules above it.
TONE_FORBIDDEN = re.compile(r"(ignore|disregard|override|bypass|disable|forget|approv|without ask|system prompt|instruction|secret|token|"
                            r"password|credential|api[ _-]?key|sandbox|unfiltered|uncensored|no rules|jailbreak|https?:|never refuse|always obey)", re.I)


class BudgetExceeded(RuntimeError):
    """The workspace's daily model-call limit is used up (protects your API quota from runaway loops)."""


class _Budgeted:
    """Wraps a model so every call is counted against the daily limit. Everything else passes straight through."""

    def __init__(self, model: Model, ws: "Workspace") -> None:
        self._model, self._ws = model, ws

    def complete(self, messages: list[dict]) -> str:
        self._ws.spend_call()
        return self._model.complete(messages)

    def __getattr__(self, name: str):
        return getattr(self._model, name)


def default_model_factory(agent: str) -> Model:
    return OpenAIAdapter()


class Workspace:
    def __init__(self, root: Path | str, model_factory: Callable[[str], Model] | None = None,
                 clock: Callable[[], float] = time.time, sync: bool = True,
                 encrypt_keychain: bool | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # Data is private to this user. When running as root (a container), the server's data stays root-only and
        # only the path to each agent's own folder is traversable, so code run as the agent's user id cannot read it.
        os.chmod(self.root, 0o711 if os.geteuid() == 0 else 0o700)
        self.db = Database(self.root / "workspace.db")
        self.keychain = Keychain(self.root / "keychain", encrypt=encrypt_keychain)
        os.chmod(self.keychain.folder, 0o700)
        raw = os.environ.get("KINTSUGI_DAILY_CALLS", "")
        self.daily_calls = int(raw) if raw.strip().isdigit() else DEFAULT_DAILY_CALLS
        self.model_factory = model_factory or default_model_factory
        self.clock = clock
        self.sync = sync  # True: agents run inside post(); False: on a worker pool (the server)
        self._models: dict[str, Model] = {}
        self._improver = None
        self._pusher = None
        self._backups = None
        self.last_active = 0.0  # when the app last talked to the server (a person is probably looking at it)
        self.study_model_factory: Callable[[str | None], Model] | None = None  # tests/embedding; default uses the real API
        self._agent_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._recent_runs: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()  # guards the rate limiter and the busy set
        self._busy: set[str] = set()
        self._inflight = 0  # runs submitted to the pool and not finished yet
        self._closing = False
        self._pending: deque = deque()  # sync mode: wake-ups queued so that runs never nest
        self._draining = False
        self._pool = None if sync else ThreadPoolExecutor(max_workers=self.parallel_limit(), thread_name_prefix="kintsugi-agent")

    # --- folders ---------------------------------------------------------

    def agent_dir(self, name: str) -> Path:
        return self.root / "agents" / name

    def files_dir(self, name: str) -> Path:
        return self.agent_dir(name) / "files"

    def www_dir(self, name: str) -> Path:
        return self.agent_dir(name) / "www"

    def lessons_path(self, name: str) -> Path:
        return self.agent_dir(name) / "lessons.json"

    # --- agents ----------------------------------------------------------

    def create_agent(self, name: str, persona: str = "", tier: str = "auto", tools: list[str] | None = None,
                     model: str | None = None) -> None:
        if len(self.list_agents()) >= MAX_AGENTS:
            raise WorkspaceError(f"at most {MAX_AGENTS} agents")
        if not NAME_RE.match(name) or name == "system":
            raise WorkspaceError("names are lowercase letters, digits, '-' and '_', start with a letter, and cannot be 'system'")
        if name in ("all", "everyone"):
            raise WorkspaceError("'all' and 'everyone' are reserved: @all wakes every agent in a room")
        if tier not in perms.TIERS:
            raise WorkspaceError(f"tier must be one of {', '.join(perms.TIERS)}")
        if self.get_agent(name, missing_ok=True):
            raise WorkspaceError(f"agent '{name}' already exists")
        from .tools import TOOLS

        if tools is not None:
            unknown = [t for t in tools if t not in TOOLS]
            if unknown:
                raise WorkspaceError(f"unknown tools: {', '.join(unknown)}")
        self.db.execute("INSERT INTO agents (name, persona, tier, tools, created, model) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, persona[:1000], tier, None if tools is None else json.dumps(tools), self.clock(),
                         self._clean_model(model)))
        self.files_dir(name).mkdir(parents=True, exist_ok=True)
        self.www_dir(name).mkdir(parents=True, exist_ok=True)
        self._lock_agent_dirs(name)
        self.audit(name, "agent-created", tier)

    def _lock_agent_dirs(self, name: str) -> None:
        """Private permissions for an agent's folders. (With the drop-user sandbox, run_python hands the folder to the
        agent's own user id for the duration of a run.)"""
        (self.root / "agents").mkdir(exist_ok=True)
        root = os.geteuid() == 0
        os.chmod(self.root / "agents", 0o711 if root else 0o700)
        os.chmod(self.agent_dir(name), 0o711 if root else 0o700)
        os.chmod(self.files_dir(name), 0o700)
        os.chmod(self.www_dir(name), 0o755 if root else 0o700)

    def get_agent(self, name: str, missing_ok: bool = False) -> dict | None:
        row = self.db.one("SELECT * FROM agents WHERE name = ?", (name,))
        if row is None:
            if missing_ok:
                return None
            raise WorkspaceError(f"no such agent: {name}")
        row["tools"] = None if row["tools"] is None else json.loads(row["tools"])
        return row

    def list_agents(self) -> list[dict]:
        return [self.get_agent(row["name"]) for row in self.db.query("SELECT name FROM agents ORDER BY name")]

    def set_tier(self, name: str, tier: str) -> None:
        if tier not in perms.TIERS:
            raise WorkspaceError(f"tier must be one of {', '.join(perms.TIERS)}")
        self.get_agent(name)
        self.db.execute("UPDATE agents SET tier = ? WHERE name = ?", (tier, name))
        self.audit(name, "tier-changed", tier)

    def set_persona(self, name: str, persona: str) -> None:
        self.get_agent(name)
        self.db.execute("UPDATE agents SET persona = ? WHERE name = ?", (persona[:1000], name))
        self.audit(name, "persona-changed")

    @staticmethod
    def _clean_model(model: str | None) -> str | None:
        model = (model or "").strip()
        if model and not re.fullmatch(r"[A-Za-z0-9._:/@+-]{1,100}", model):
            raise WorkspaceError("model names use letters, digits and . _ : / @ + -")
        return model or None

    def set_model(self, name: str, model: str | None, provider: str | None = None) -> None:
        """Choose which model (and which saved provider) an agent uses. None = the workspace default."""
        self.get_agent(name)
        provider = (provider or "").strip() or None
        if provider and provider not in self._provider_state()["profiles"]:
            raise WorkspaceError(f"there is no saved provider named '{provider}' (add it in Settings > Models)")
        self.db.execute("UPDATE agents SET model = ?, provider = ? WHERE name = ?", (self._clean_model(model), provider, name))
        self._models.pop(name, None)
        self.audit(name, "model-changed", f"{provider or 'default provider'} / {model or 'default model'}")

    # --- model providers: the owner's own keys (write-only, kept in the keychain, sent only to that provider) ---

    def _provider_state(self) -> dict:
        try:
            state = json.loads(self.get_setting("providers", "") or "{}")
        except json.JSONDecodeError:
            state = {}
        profiles = state.get("profiles") if isinstance(state.get("profiles"), dict) else {}
        default = state.get("default") if state.get("default") in profiles else None
        return {"default": default, "profiles": profiles}

    @staticmethod
    def _provider_key_name(pid: str) -> str:
        return "PROVIDER_" + pid.upper().replace("-", "_") + "_KEY"

    def _provider_key(self, pid: str) -> str | None:
        name = self._provider_key_name(pid)
        return self.keychain.env_for(self.SEARCH_AGENT, [name])[name] if name in self.keychain.names(self.SEARCH_AGENT) else None

    def providers(self) -> dict:
        state = self._provider_state()
        rows = [{"id": pid, "label": p.get("label") or pid, "kind": p["kind"], "base_url": p["base_url"], "model": p.get("model", ""),
                 "keyless": bool(p.get("keyless")), "has_key": self._provider_key(pid) is not None, "default": pid == state["default"]}
                for pid, p in state["profiles"].items()]
        env = bool(os.environ.get("KINTSUGI_API_KEY") or os.environ.get("GROQ_API_KEY"))
        return {"profiles": rows, "default": state["default"], "env_fallback": env,
                "presets": {k: {kk: v.get(kk, "") for kk in ("label", "kind", "base_url", "model", "signup", "keyless")} for k, v in providers.PRESETS.items()}}

    def set_provider(self, pid: str, kind: str, base_url: str, model: str = "", key: str | None = None,
                     label: str = "", keyless: bool = False, make_default: bool = False) -> dict:
        pid = (pid or "").strip().lower()
        if not providers.ID_RE.match(pid):
            raise WorkspaceError("a provider name is 2-24 characters: lowercase letters, digits and '-', starting with a letter")
        if kind not in providers.KINDS:
            raise WorkspaceError("kind must be one of: " + ", ".join(providers.KINDS))
        try:
            base_url, model = providers.clean_base_url(base_url), providers.clean_model(model)
        except providers.ProviderError as err:
            raise WorkspaceError(str(err)) from None
        state = self._provider_state()
        if pid not in state["profiles"] and len(state["profiles"]) >= 12:
            raise WorkspaceError("at most 12 providers")
        if key:
            self.keychain.set(self.SEARCH_AGENT, self._provider_key_name(pid), key.strip())
        if not keyless and self._provider_key(pid) is None:
            raise WorkspaceError("paste your API key for this provider (it is stored in your keychain and never shown again)")
        state["profiles"][pid] = {"kind": kind, "base_url": base_url, "model": model, "label": (label or pid)[:60], "keyless": bool(keyless)}
        if make_default or state["default"] is None:
            state["default"] = pid
        self.set_setting("providers", json.dumps(state))
        self._models.clear()
        self.audit(None, "provider-saved", f"{pid} {kind} {base_url}" + (" key-updated" if key else ""))
        return self.providers()

    def remove_provider(self, pid: str) -> dict:
        state = self._provider_state()
        if pid not in state["profiles"]:
            raise WorkspaceError("no such provider")
        del state["profiles"][pid]
        state["default"] = state["default"] if state["default"] != pid else next(iter(state["profiles"]), None)
        self.keychain.delete(self.SEARCH_AGENT, self._provider_key_name(pid))
        self.db.execute("UPDATE agents SET provider = NULL WHERE provider = ?", (pid,))
        self.set_setting("providers", json.dumps(state))
        self._models.clear()
        self.audit(None, "provider-removed", pid)
        return self.providers()

    def set_default_provider(self, pid: str) -> dict:
        state = self._provider_state()
        if pid not in state["profiles"]:
            raise WorkspaceError("no such provider")
        state["default"] = pid
        self.set_setting("providers", json.dumps(state))
        self._models.clear()
        return self.providers()

    def build_model(self, provider: str | None = None, model: str | None = None) -> Model:
        """A real model from the saved providers (or, if none are saved, the KINTSUGI_API_KEY environment settings)."""
        state = self._provider_state()
        pid = provider if provider in state["profiles"] else state["default"]
        if pid is None:
            if not state["profiles"]:
                try:
                    return OpenAIAdapter(model=model) if model else OpenAIAdapter()
                except RuntimeError:
                    raise providers.ProviderError("No AI model is set up yet. Open Settings > Models and add your API key.") from None
            pid = next(iter(state["profiles"]))
        profile = state["profiles"][pid]
        key = self._provider_key(pid)
        if key is None and not profile.get("keyless"):
            raise providers.ProviderError(f"The provider '{pid}' has no API key. Open Settings > Models and paste it.")
        return providers.build(profile, key, model)

    def test_provider(self, pid: str, model: str | None = None) -> dict:
        """Ask the model to say OK (proves key, address and model) and list the models this key can use."""
        state = self._provider_state()
        if pid not in state["profiles"]:
            raise WorkspaceError("no such provider")
        listing: list[str] = []
        try:
            adapter = self.build_model(pid, model or state["profiles"][pid].get("model") or "list-only")
            try:
                listing = adapter.list_models()
            except Exception:  # not every service lists models; the real test is below
                listing = []
            chosen = model or state["profiles"][pid].get("model") or ""
            if not chosen:
                return {"ok": True, "models": listing, "reply": "", "note": "The key works. Choose a model, then test again."} if listing else \
                    {"ok": False, "models": [], "reply": "", "error": "Type a model name, then test again."}
            reply = self.build_model(pid, chosen).complete([{"role": "user", "content": "Reply with the single word OK."}])
        except providers.ProviderError as err:
            return {"ok": False, "models": listing, "reply": "", "error": str(err)}
        except (ModelRequestError, ModelInfraError, QuotaExhausted, RuntimeError) as err:
            return {"ok": False, "models": listing, "reply": "", "error": self.keychain.redact(self.SEARCH_AGENT, str(err))[:400]}
        return {"ok": True, "models": listing, "reply": reply[:80]}

    def set_playbook(self, name: str, playbook: str) -> None:
        """The rules an agent has learned. Plain text only; it can never change permissions or tools."""
        self.get_agent(name)
        self.db.execute("UPDATE agents SET playbook = ? WHERE name = ?", (playbook[:1500], name))
        self.audit(name, "playbook-changed", f"{len(playbook)} characters")

    # --- the tone each person chooses for the replies they get ---------------------

    def get_tone(self, user: str = "you") -> dict:
        raw = self.get_setting(f"tone:{user}", "") or self.get_setting("tone:you", "")
        try:
            saved = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            saved = {}
        style = saved.get("style") if saved.get("style") in TONE_LABELS else DEFAULT_TONE
        return {"style": style, "custom": saved.get("custom", "")}

    def set_tone(self, user: str, style: str, custom: str = "") -> dict:
        if style not in TONE_LABELS:
            raise WorkspaceError("style must be one of: " + ", ".join(TONE_LABELS))
        custom = " ".join(str(custom).split())[:300]
        if style == "custom":
            if len(custom) < 5:
                raise WorkspaceError("describe the style you want in a few words")
            if TONE_FORBIDDEN.search(custom):
                raise WorkspaceError("a style can change how replies sound, not the rules. Remove words about ignoring rules, "
                                     "approvals, secrets, the sandbox, links or instructions.")
        self.set_setting(f"tone:{user}", json.dumps({"style": style, "custom": custom}))
        self.audit(None, "tone-changed", f"{user}: {style}")
        return self.get_tone(user)

    def tone_text(self, user: str = "you") -> str:
        """The sentence added to an agent's prompt for this person's replies (style only, never rules)."""
        tone = self.get_tone(user)
        if tone["style"] == "custom" and tone["custom"] and not TONE_FORBIDDEN.search(tone["custom"]):
            return tone["custom"]
        return TONES.get(tone["style"], TONES[DEFAULT_TONE])

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.db.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value))

    def study_model(self, model_name: str | None) -> Model:
        """A fresh model for a study run (not tied to an agent, not counted against the daily cap by itself)."""
        if self.study_model_factory is not None:
            return self.study_model_factory(model_name)
        if self.model_factory is default_model_factory:
            return self.build_model(None, model_name)
        return self.model_factory(model_name or "study")

    @property
    def pusher(self):
        from .push import Push

        if self._pusher is None:
            self._pusher = Push(self)
        return self._pusher

    def touch(self) -> None:
        self.last_active = time.time()

    def notify_if_away(self, reason: str) -> None:
        """Wake the owner's phone (text-free) when something needs them and they are not using the app right now."""
        if time.time() - self.last_active < 90:
            return
        try:
            if self.pusher.count():
                threading.Thread(target=self.pusher.notify, args=(reason,), daemon=True).start()
        except Exception as err:  # a notification problem must never break messaging
            self.audit(None, "push-error", f"{type(err).__name__}: {str(err)[:150]}")

    @property
    def plugins(self):
        from .plugins import Plugins

        if getattr(self, "_plugins", None) is None:
            self._plugins = Plugins(self)
        return self._plugins

    @property
    def backups(self):
        from .backup import Backups

        if self._backups is None:
            self._backups = Backups(self)
        return self._backups

    @property
    def improver(self):
        from .improve import Improver

        if self._improver is None:
            self._improver = Improver(self)
        return self._improver

    def model_for(self, agent: str) -> Model:
        if agent not in self._models:
            if self.model_factory is default_model_factory:  # the real API: honour the agent's own provider and model choice
                row = self.get_agent(agent)
                base = self.build_model(row["provider"], row["model"])
            else:
                base = self.model_factory(agent)
            self._models[agent] = _Budgeted(base, self)
        return self._models[agent]

    def provider(self) -> str:
        """Where conversation text is sent when an agent thinks: the model provider's host."""
        if self.model_factory is not default_model_factory:
            return "a custom model (not the default API)"
        from kintsugi.model import DEFAULT_BASE_URL
        from urllib.parse import urlparse

        return urlparse(os.environ.get("KINTSUGI_BASE_URL") or DEFAULT_BASE_URL).netloc

    # --- daily model-call budget ------------------------------------------

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    def calls_today(self) -> int:
        row = self.db.one("SELECT calls FROM usage WHERE day = ?", (self._day(),))
        return row["calls"] if row else 0

    def spend_call(self) -> None:
        """Count one model call; raise BudgetExceeded when the daily limit is used up."""
        with self._lock:
            if self.daily_calls and self.calls_today() >= self.daily_calls:
                raise BudgetExceeded(f"the daily limit of {self.daily_calls} model calls is used up "
                                     "(raise it with KINTSUGI_DAILY_CALLS, or wait until tomorrow, UTC)")
            self.db.execute("INSERT INTO usage (day, calls) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
                            (self._day(),))

    # --- web search (the owner's own key; counted per day) --------------------------

    SEARCH_AGENT = "_workspace"  # the keychain slot for workspace-wide keys (agents cannot have this name)

    def search_settings(self) -> dict:
        raw = self.get_setting("search", "")
        try:
            saved = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            saved = {}
        return {"provider": saved.get("provider") if saved.get("provider") in ("tavily", "brave") else "tavily",
                "daily_cap": min(max(int(saved.get("daily_cap", 50)), 1), 1000),
                "configured": "SEARCH_API_KEY" in self.keychain.names(self.SEARCH_AGENT)}

    def set_search(self, provider: str, key: str | None = None, daily_cap: int | None = None) -> dict:
        from .websearch import PROVIDERS

        if provider not in PROVIDERS:
            raise WorkspaceError("provider must be one of: " + ", ".join(PROVIDERS))
        current = self.search_settings()
        cap = current["daily_cap"] if daily_cap is None else min(max(int(daily_cap), 1), 1000)
        if key:
            self.keychain.set(self.SEARCH_AGENT, "SEARCH_API_KEY", key.strip())
        self.set_setting("search", json.dumps({"provider": provider, "daily_cap": cap}))
        self.audit(None, "search-settings", f"{provider} cap={cap}" + (" key-updated" if key else ""))
        return self.search_settings()

    def remove_search_key(self) -> None:
        self.keychain.delete(self.SEARCH_AGENT, "SEARCH_API_KEY")
        self.audit(None, "search-key-removed")

    def searches_today(self) -> int:
        row = self.db.one("SELECT calls FROM usage WHERE day = ?", (f"search-{self._day()}",))
        return row["calls"] if row else 0

    def spend_search(self) -> None:
        """Count one web search; refuse when today's allowance (set by the owner) is used up."""
        with self._lock:
            cap = self.search_settings()["daily_cap"]
            if self.searches_today() >= cap:
                raise WorkspaceError(f"today's limit of {cap} web searches is used up (the owner can raise it in Settings > Search)")
            self.db.execute("INSERT INTO usage (day, calls) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
                            (f"search-{self._day()}",))

    # --- agents working at the same time ---

    MAX_PARALLEL = 8

    def parallel_limit(self) -> int:
        """How many agents may think at once (different agents run in parallel; one agent never runs twice at once)."""
        raw = self.get_setting("parallel", "") or os.environ.get("KINTSUGI_PARALLEL", "")
        return min(max(int(raw), 1), self.MAX_PARALLEL) if raw.strip().isdigit() else 4

    def set_parallel(self, limit: int) -> int:
        limit = min(max(int(limit), 1), self.MAX_PARALLEL)
        self.set_setting("parallel", str(limit))
        if self._pool is not None:  # new work goes to the new pool; runs already started finish on the old one
            with self._lock:
                old, self._pool = self._pool, ThreadPoolExecutor(max_workers=limit, thread_name_prefix="kintsugi-agent")
            old.shutdown(wait=False)
        self.audit(None, "parallel-changed", str(limit))
        return limit

    # --- internet access for agents: the owner decides (workspace switch + per agent Off / Ask / Allow) ---

    INTERNET_MODES = ("off", "ask", "allow")

    def internet_settings(self) -> dict:
        try:
            saved = json.loads(self.get_setting("internet", "") or "{}")
        except json.JSONDecodeError:
            saved = {}
        return {"enabled": bool(saved.get("enabled", True)), "fetch_cap": min(max(int(saved.get("fetch_cap", 60)), 1), 1000),
                "fetched_today": self.fetches_today()}

    def set_internet(self, enabled: bool | None = None, fetch_cap: int | None = None) -> dict:
        current = self.internet_settings()
        enabled = current["enabled"] if enabled is None else bool(enabled)
        cap = current["fetch_cap"] if fetch_cap is None else min(max(int(fetch_cap), 1), 1000)
        self.set_setting("internet", json.dumps({"enabled": enabled, "fetch_cap": cap}))
        self.audit(None, "internet-settings", f"enabled={enabled} fetch_cap={cap}")
        return self.internet_settings()

    def set_agent_internet(self, name: str, mode: str) -> None:
        self.get_agent(name)
        if mode not in self.INTERNET_MODES:
            raise WorkspaceError("internet access must be one of: " + ", ".join(self.INTERNET_MODES))
        self.db.execute("UPDATE agents SET internet = ? WHERE name = ?", (mode, name))
        self.audit(name, "internet-changed", mode)

    def internet_mode(self, name: str) -> str:
        """What this agent may do online right now: off, ask or allow (the workspace switch overrides everything)."""
        if not self.internet_settings()["enabled"]:
            return "off"
        mode = self.get_agent(name)["internet"]
        return mode if mode in self.INTERNET_MODES else "off"

    def fetches_today(self) -> int:
        row = self.db.one("SELECT calls FROM usage WHERE day = ?", (f"fetch-{self._day()}",))
        return row["calls"] if row else 0

    def spend_fetch(self) -> None:
        with self._lock:
            cap = self.internet_settings()["fetch_cap"]
            if self.fetches_today() >= cap:
                raise WorkspaceError(f"today's limit of {cap} page fetches is used up (the owner can raise it in Settings > Internet)")
            self.db.execute("INSERT INTO usage (day, calls) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET calls = calls + 1",
                            (f"fetch-{self._day()}",))

    def web_search(self, query: str, count: int = 5) -> list[dict]:
        """Run one search with the owner's key. Raises SearchError/WorkspaceError with messages fit to show."""
        from .websearch import SearchError, search

        settings = self.search_settings()
        if not settings["configured"]:
            raise SearchError("web search is not set up (the owner adds a search key in Settings > Search)")
        self.spend_search()
        key = self.keychain.env_for(self.SEARCH_AGENT, ["SEARCH_API_KEY"])["SEARCH_API_KEY"]
        return search(settings["provider"], key, query, count)

    # --- deleting data (privacy) ---------------------------------------------

    def delete_agent(self, name: str) -> None:
        """Remove an agent and everything it owns: files, apps, lessons, notes, secrets, jobs, approvals,
        its direct messages and the messages it wrote."""
        self.get_agent(name)
        dms = [r["room"] for r in self.db.query("SELECT room FROM members WHERE member = ?", (name,))
               if r["room"].startswith("dm-")]
        for room in dms:
            self.delete_room(room)
        for table in ("notes", "jobs", "approvals"):
            self.db.execute(f"DELETE FROM {table} WHERE agent = ?", (name,))
        self.db.execute("DELETE FROM messages WHERE sender = ?", (name,))
        self.db.execute("DELETE FROM members WHERE member = ?", (name,))
        self.db.execute("DELETE FROM audit WHERE agent = ?", (name,))
        self.db.execute("DELETE FROM agents WHERE name = ?", (name,))
        shutil.rmtree(self.agent_dir(name), ignore_errors=True)
        (self.keychain.folder / f"{name}.json").unlink(missing_ok=True)
        self._models.pop(name, None)
        self.audit(None, "agent-deleted", name)

    def delete_room(self, room: str) -> None:
        self._require_room(room)
        for table in ("messages", "members", "jobs", "approvals"):
            self.db.execute(f"DELETE FROM {table} WHERE room = ?", (room,))
        self.db.execute("DELETE FROM rooms WHERE name = ?", (room,))
        self.audit(None, "room-deleted", room)

    def purge_messages(self, older_than_days: float) -> int:
        """Delete messages older than the given number of days (and old audit entries). Returns how many messages."""
        cutoff = self.clock() - older_than_days * 86400
        count = self.db.one("SELECT COUNT(*) AS n FROM messages WHERE ts < ?", (cutoff,))["n"]
        self.db.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
        self.db.execute("DELETE FROM audit WHERE ts < ?", (cutoff,))
        self.audit(None, "purged", f"{count} messages older than {older_than_days:g} days")
        return count

    # --- rooms -----------------------------------------------------------

    def create_room(self, name: str, members: list[str] | tuple = ()) -> None:
        if len(self.list_rooms()) >= MAX_ROOMS:
            raise WorkspaceError(f"at most {MAX_ROOMS} rooms")
        if not NAME_RE.match(name) or name.startswith("dm-"):
            raise WorkspaceError("room names are lowercase letters, digits, '-' and '_' (and cannot start with 'dm-')")
        if self.db.one("SELECT 1 FROM rooms WHERE name = ?", (name,)):
            raise WorkspaceError(f"room '{name}' already exists")
        self.db.execute("INSERT INTO rooms (name, kind, created) VALUES (?, 'room', ?)", (name, self.clock()))
        for member in members:
            self.add_member(name, member)

    def open_dm(self, a: str, b: str) -> str:
        """The direct-message room between two names (people or agents); created on first use."""
        if a == b:
            raise WorkspaceError("a direct message needs two different names")
        name = "dm-" + "-".join(sorted([a, b]))
        if not self.db.one("SELECT 1 FROM rooms WHERE name = ?", (name,)):
            self.db.execute("INSERT INTO rooms (name, kind, created) VALUES (?, 'dm', ?)", (name, self.clock()))
            self.db.execute("INSERT OR IGNORE INTO members (room, member) VALUES (?, ?)", (name, a))
            self.db.execute("INSERT OR IGNORE INTO members (room, member) VALUES (?, ?)", (name, b))
        return name

    def add_member(self, room: str, member: str) -> None:
        self._require_room(room)
        if not (HUMAN_RE.match(member) or NAME_RE.match(member)):
            raise WorkspaceError(f"bad member name: {member!r}")
        self.db.execute("INSERT OR IGNORE INTO members (room, member) VALUES (?, ?)", (room, member))

    def members(self, room: str) -> list[str]:
        return [r["member"] for r in self.db.query("SELECT member FROM members WHERE room = ? ORDER BY member", (room,))]

    def list_rooms(self) -> list[dict]:
        return self.db.query("SELECT name, kind FROM rooms ORDER BY kind, name")

    def _require_room(self, room: str) -> dict:
        row = self.db.one("SELECT * FROM rooms WHERE name = ?", (room,))
        if row is None:
            raise WorkspaceError(f"no such room: {room}")
        return row

    # --- messages and routing -------------------------------------------

    def history(self, room: str, after: int = 0, limit: int = 50) -> list[dict]:
        self._require_room(room)
        rows = self.db.query("SELECT * FROM messages WHERE room = ? AND id > ? ORDER BY id DESC LIMIT ?",
                             (room, after, limit))
        return list(reversed(rows))

    def post(self, room: str, sender: str, text: str, hops: int = 0, human: bool = False) -> int:
        """Add a message and wake the agents it is addressed to. `human=True` forbids posing as an agent."""
        kind = self._require_room(room)["kind"]
        text = text.strip()
        if not text:
            raise WorkspaceError("empty message")
        if len(text) > MAX_MESSAGE_CHARS:
            raise WorkspaceError(f"messages are limited to {MAX_MESSAGE_CHARS} characters")
        is_agent = self.get_agent(sender, missing_ok=True) is not None
        if is_agent:
            text = self.keychain.redact(sender, text)  # an agent can never post a secret it has been given
        if human and (is_agent or not HUMAN_RE.match(sender) or sender == "system" or sender.startswith("cron-")):
            raise WorkspaceError("that sender name is not available to people")
        if is_agent and sender not in self.members(room):
            raise WorkspaceError(f"agent '{sender}' is not a member of '{room}'")
        message_id = self.db.execute("INSERT INTO messages (room, sender, text, ts, hops) VALUES (?, ?, ?, ?, ?)",
                                     (room, sender, text, self.clock(), hops))
        if is_agent:
            self.notify_if_away("message")
        for agent in self._targets(room, kind, sender, text):
            if hops >= MAX_HOPS:
                self.audit(agent, "loop-guard", f"{room}: not waking {agent} after {hops} hops")
                continue
            self._dispatch(agent, room, message_id, hops + 1)
        return message_id

    def _targets(self, room: str, kind: str, sender: str, text: str) -> list[str]:
        members = set(self.members(room))
        wanted = set(MENTION_RE.findall(text))
        if wanted & {"all", "everyone"}:  # @all wakes every agent in the room; they work at the same time
            wanted |= members
        if kind == "dm":
            wanted |= members
        return sorted(a for a in wanted if a != sender and a in members and self.get_agent(a, missing_ok=True))

    def _dispatch(self, agent: str, room: str, message_id: int, hops: int) -> None:
        now = self.clock()
        with self._lock:
            recent = self._recent_runs[agent]
            while recent and now - recent[0] > 60:
                recent.popleft()
            limited = len(recent) >= MAX_RUNS_PER_MINUTE
            if not limited:
                recent.append(now)
        if limited:
            self.audit(agent, "rate-limited", room)
            return
        if not self.sync:
            with self._lock:
                if self._closing:
                    return
                self._inflight += 1
                pool = self._pool
            pool.submit(self._run_async, agent, room, message_id, hops)
            return
        # Single-threaded mode: an agent's reply may wake another agent (or the same one again). Queue
        # the wake-up and let the outermost call work through the queue, so runs never nest.
        self._pending.append((agent, room, message_id, hops))
        if self._draining:
            return
        self._draining = True
        try:
            while self._pending:
                self._run(*self._pending.popleft())
        finally:
            self._draining = False

    def _run(self, agent: str, room: str, message_id: int, hops: int) -> None:
        from .agents import run_agent

        with self._lock:
            self._busy.add(agent)
        try:
            with self._agent_locks[agent]:
                try:
                    run_agent(self, agent, room, message_id, hops)
                except (ModelInfraError, QuotaExhausted, ModelRequestError, RuntimeError) as err:
                    self._run_failed(agent, room, hops, f"{agent} could not get an answer from the model: {err}", err)
                except Exception as err:  # a bug must show up in the room, never vanish on a worker thread
                    self._run_failed(agent, room, hops, f"{agent} hit an internal error: {type(err).__name__}: {err}", err)
        finally:
            with self._lock:
                self._busy.discard(agent)

    def _run_async(self, agent: str, room: str, message_id: int, hops: int) -> None:
        try:
            self._run(agent, room, message_id, hops)
        finally:
            with self._lock:
                self._inflight -= 1

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Block until no agent run is queued or running (worker-pool mode). Returns False on timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if self._inflight == 0:
                    return True
            time.sleep(0.02)
        return False

    def _run_failed(self, agent: str, room: str, hops: int, notice: str, err: Exception) -> None:
        self.audit(agent, "run-error", f"{type(err).__name__}: {err}"[:300])
        self.db.execute("INSERT INTO messages (room, sender, text, ts, hops) VALUES (?, 'system', ?, ?, ?)",
                        (room, notice[:400], self.clock(), hops))

    def busy(self) -> list[str]:
        """Agents that are working on a message right now."""
        with self._lock:
            return sorted(self._busy)

    # --- approvals -------------------------------------------------------

    def request_approval(self, agent: str, room: str, tool: str, args: dict) -> int:
        self.notify_if_away("approval")
        return self.db.execute("INSERT INTO approvals (agent, room, tool, args, ts) VALUES (?, ?, ?, ?, ?)",
                               (agent, room, tool, json.dumps(args), self.clock()))

    def approvals(self, status: str | None = "pending") -> list[dict]:
        if status is None:
            return self.db.query("SELECT * FROM approvals ORDER BY id")
        return self.db.query("SELECT * FROM approvals WHERE status = ? ORDER BY id", (status,))

    def decide(self, approval_id: int, approve: bool, by: str = "human") -> str:
        """Approve (runs the tool now) or deny a waiting tool call. Returns the tool's output."""
        from .tools import Ctx, execute

        row = self.db.one("SELECT * FROM approvals WHERE id = ?", (approval_id,))
        if row is None:
            raise WorkspaceError(f"no such approval: {approval_id}")
        if row["status"] != "pending":
            raise WorkspaceError(f"approval {approval_id} was already {row['status']}")
        if not approve:
            self.db.execute("UPDATE approvals SET status = 'denied', decided_by = ?, result = 'denied' WHERE id = ?",
                            (by, approval_id))
            self.audit(row["agent"], "approval-denied", f"#{approval_id} {row['tool']}")
            self.post_system(row["room"], f"#{approval_id}: {row['agent']} was not allowed to run {row['tool']}.")
            self._resume(row, "A person denied it. Carry on without it, or ask what else would help.")
            return "denied"
        self.db.execute("UPDATE approvals SET status = 'approved', decided_by = ? WHERE id = ?", (by, approval_id))
        ctx = Ctx(self, row["agent"], row["room"], hops=0, situation=f"approval#{approval_id}")
        outcome = execute(ctx, row["tool"], json.loads(row["args"]), approved=True)
        self.db.execute("UPDATE approvals SET result = ? WHERE id = ?", (outcome.output[:2000], approval_id))
        self.audit(row["agent"], "approval-granted", f"#{approval_id} {row['tool']} -> {outcome.status}")
        self._resume(row, f"A person approved it and it finished ({outcome.status}). Output:\n{outcome.output[:1500]}")
        return outcome.output

    def _resume(self, approval: dict, news: str) -> None:
        """Wake the agent that asked, so it can use the result instead of leaving the task half done."""
        text = f"@{approval['agent']} Your request to run {approval['tool']} (approval #{approval['id']}). {news}"
        self.post(approval["room"], "system", text[:MAX_MESSAGE_CHARS])

    def post_system(self, room: str, text: str) -> None:
        """A notice from the workspace itself. It never wakes an agent."""
        self.db.execute("INSERT INTO messages (room, sender, text, ts, hops) VALUES (?, 'system', ?, ?, ?)",
                        (room, text[:MAX_MESSAGE_CHARS], self.clock(), MAX_HOPS))

    # --- notes (an agent's own scratch memory) --------------------------

    def add_note(self, agent: str, text: str) -> int:
        return self.db.execute("INSERT INTO notes (agent, text, ts) VALUES (?, ?, ?)", (agent, text, self.clock()))

    def search_notes(self, agent: str, query: str, limit: int = 5) -> list[dict]:
        wanted = tokens(query)
        scored = []
        for note in self.db.query("SELECT * FROM notes WHERE agent = ? ORDER BY id DESC LIMIT 500", (agent,)):
            overlap = len(wanted & tokens(note["text"]))
            if overlap:
                scored.append((overlap, note["id"], note))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return [note for _, _, note in scored[:limit]]

    # --- jobs ------------------------------------------------------------

    def add_job(self, agent: str, room: str, cron: str, prompt: str, kind: str = "custom", title: str = "", owner: str = "you") -> int:
        from .scheduler import parse_cron

        self.get_agent(agent)
        self._require_room(room)
        parse_cron(cron)
        return self.db.execute("INSERT INTO jobs (agent, room, cron, prompt, kind, title, owner) VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (agent, room, cron, prompt, kind, title[:120], owner))

    def list_jobs(self, agent: str | None = None) -> list[dict]:
        if agent is None:
            return self.db.query("SELECT * FROM jobs ORDER BY id")
        return self.db.query("SELECT * FROM jobs WHERE agent = ? ORDER BY id", (agent,))

    def remove_job(self, job_id: int) -> None:
        self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def mark_job_run(self, job_id: int, minute_number: int, ts: float | None = None) -> None:
        self.db.execute("UPDATE jobs SET last_run_minute = ?, last_run_ts = ?, runs = runs + 1 WHERE id = ?",
                        (minute_number, self.clock() if ts is None else ts, job_id))

    def set_job_enabled(self, job_id: int, enabled: bool) -> None:
        if not self.db.one("SELECT 1 FROM jobs WHERE id = ?", (job_id,)):
            raise WorkspaceError(f"no such job: {job_id}")
        self.db.execute("UPDATE jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, job_id))
        self.audit(None, "job-enabled" if enabled else "job-paused", f"job {job_id}")

    def run_job_now(self, job_id: int) -> int:
        """Run an automation immediately, exactly as the schedule would (it is posted into its room)."""
        job = self.db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if job is None:
            raise WorkspaceError(f"no such job: {job_id}")
        now = self.clock()
        self.mark_job_run(job_id, int(now // 60), now)
        self.audit(job["agent"], "cron-fired", f"job {job_id} (run now)")
        return self.post(job["room"], f"cron-{job_id}", f"@{job['agent']} {job['prompt']}")

    # --- time zone (so "every morning at 8" means the owner's morning) ---------------

    def get_timezone(self) -> dict:
        raw = self.get_setting("timezone", "")
        try:
            saved = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            saved = {}
        return {"name": str(saved.get("name", "")), "offset_minutes": int(saved.get("offset_minutes", 0)), "set": bool(saved)}

    def set_timezone(self, name: str, offset_minutes: int = 0) -> dict:
        name = str(name or "").strip()
        offset = max(-840, min(840, int(offset_minutes)))
        if name:
            if len(name) > 64 or not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z0-9_+-]+){0,2}|UTC", name):
                raise WorkspaceError("time zone names look like Asia/Kolkata or Europe/Berlin")
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(name)
            except Exception:
                pass  # no zone database on this system: the offset the phone reported is used instead
        self.set_setting("timezone", json.dumps({"name": name, "offset_minutes": offset}))
        self.audit(None, "timezone-changed", name or f"UTC{offset:+d}min")
        return self.get_timezone()

    def local_datetime(self, ts: float):
        """`ts` as a clock time in the owner's time zone (the server's own zone if none was chosen)."""
        from datetime import datetime, timedelta, timezone

        tz = self.get_timezone()
        if not tz["set"]:
            return datetime.fromtimestamp(ts)
        if tz["name"]:
            try:
                from zoneinfo import ZoneInfo

                return datetime.fromtimestamp(ts, ZoneInfo(tz["name"]))
            except Exception:
                pass
        return datetime.fromtimestamp(ts, timezone(timedelta(minutes=tz["offset_minutes"])))

    # --- audit and shutdown ---------------------------------------------

    def audit(self, agent: str | None, event: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO audit (ts, agent, event, detail) VALUES (?, ?, ?, ?)",
                        (self.clock(), agent, event, detail[:500]))

    def audit_log(self, limit: int = 100) -> list[dict]:
        return list(reversed(self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))))

    def close(self) -> None:
        if self._improver is not None:
            self._improver.stop()
        if self._backups is not None:
            self._backups.stop()
        if self._pool is not None:
            self.wait_idle(15)  # let running conversations finish before refusing new wake-ups
            with self._lock:
                self._closing = True
            self._pool.shutdown(wait=True)
        self.db.close()
