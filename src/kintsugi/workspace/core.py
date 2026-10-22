"""The workspace: agents, rooms, direct messages, approvals and jobs, and the routing between them.

People and agents talk in rooms. A message wakes an agent when it is addressed to it: an @mention in a
room, or any message in a direct-message room. Agent replies carry a "hop" count, and a thread of
agents answering agents stops after MAX_HOPS, so two agents can never chat forever.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from kintsugi.memory import tokens
from kintsugi.model import Model, ModelInfraError, ModelRequestError, OpenAIAdapter, QuotaExhausted

from . import perms
from .db import Database
from .keychain import Keychain

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
HUMAN_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,40}$")
MENTION_RE = re.compile(r"(?<![\w@])@([a-z][a-z0-9_-]*)")
MAX_HOPS = 4  # agent-to-agent replies in a row before the thread goes quiet
MAX_RUNS_PER_MINUTE = 20  # per agent
MAX_MESSAGE_CHARS = 4000


class WorkspaceError(ValueError):
    """A request the workspace refuses (unknown agent, bad name, not a member...)."""


def default_model_factory(agent: str) -> Model:
    return OpenAIAdapter()


class Workspace:
    def __init__(self, root: Path | str, model_factory: Callable[[str], Model] | None = None,
                 clock: Callable[[], float] = time.time, sync: bool = True,
                 encrypt_keychain: bool | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.root / "workspace.db")
        self.keychain = Keychain(self.root / "keychain", encrypt=encrypt_keychain)
        self.model_factory = model_factory or default_model_factory
        self.clock = clock
        self.sync = sync  # True: agents run inside post(); False: on a worker pool (the server)
        self._models: dict[str, Model] = {}
        self._agent_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._recent_runs: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()  # guards the rate limiter and the busy set
        self._busy: set[str] = set()
        self._inflight = 0  # runs submitted to the pool and not finished yet
        self._closing = False
        self._pending: deque = deque()  # sync mode: wake-ups queued so that runs never nest
        self._draining = False
        self._pool = None if sync else ThreadPoolExecutor(max_workers=4, thread_name_prefix="kintsugi-agent")

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

    def create_agent(self, name: str, persona: str = "", tier: str = "auto", tools: list[str] | None = None) -> None:
        if not NAME_RE.match(name) or name == "system":
            raise WorkspaceError("names are lowercase letters, digits, '-' and '_', start with a letter, and cannot be 'system'")
        if tier not in perms.TIERS:
            raise WorkspaceError(f"tier must be one of {', '.join(perms.TIERS)}")
        if self.get_agent(name, missing_ok=True):
            raise WorkspaceError(f"agent '{name}' already exists")
        from .tools import TOOLS

        if tools is not None:
            unknown = [t for t in tools if t not in TOOLS]
            if unknown:
                raise WorkspaceError(f"unknown tools: {', '.join(unknown)}")
        self.db.execute("INSERT INTO agents (name, persona, tier, tools, created) VALUES (?, ?, ?, ?, ?)",
                        (name, persona[:1000], tier, None if tools is None else json.dumps(tools), self.clock()))
        self.files_dir(name).mkdir(parents=True, exist_ok=True)
        self.www_dir(name).mkdir(parents=True, exist_ok=True)
        self.audit(name, "agent-created", tier)

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

    def model_for(self, agent: str) -> Model:
        if agent not in self._models:
            self._models[agent] = self.model_factory(agent)
        return self._models[agent]

    # --- rooms -----------------------------------------------------------

    def create_room(self, name: str, members: list[str] | tuple = ()) -> None:
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
        for agent in self._targets(room, kind, sender, text):
            if hops >= MAX_HOPS:
                self.audit(agent, "loop-guard", f"{room}: not waking {agent} after {hops} hops")
                continue
            self._dispatch(agent, room, message_id, hops + 1)
        return message_id

    def _targets(self, room: str, kind: str, sender: str, text: str) -> list[str]:
        members = set(self.members(room))
        wanted = set(MENTION_RE.findall(text))
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
            self._pool.submit(self._run_async, agent, room, message_id, hops)
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

    def add_job(self, agent: str, room: str, cron: str, prompt: str) -> int:
        from .scheduler import parse_cron

        self.get_agent(agent)
        self._require_room(room)
        parse_cron(cron)
        return self.db.execute("INSERT INTO jobs (agent, room, cron, prompt) VALUES (?, ?, ?, ?)",
                               (agent, room, cron, prompt))

    def list_jobs(self, agent: str | None = None) -> list[dict]:
        if agent is None:
            return self.db.query("SELECT * FROM jobs ORDER BY id")
        return self.db.query("SELECT * FROM jobs WHERE agent = ? ORDER BY id", (agent,))

    def remove_job(self, job_id: int) -> None:
        self.db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))

    def mark_job_run(self, job_id: int, minute_number: int) -> None:
        self.db.execute("UPDATE jobs SET last_run_minute = ? WHERE id = ?", (minute_number, job_id))

    # --- audit and shutdown ---------------------------------------------

    def audit(self, agent: str | None, event: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO audit (ts, agent, event, detail) VALUES (?, ?, ?, ?)",
                        (self.clock(), agent, event, detail[:500]))

    def audit_log(self, limit: int = 100) -> list[dict]:
        return list(reversed(self.db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))))

    def close(self) -> None:
        if self._pool is not None:
            self.wait_idle(15)  # let running conversations finish before refusing new wake-ups
            with self._lock:
                self._closing = True
            self._pool.shutdown(wait=True)
        self.db.close()
