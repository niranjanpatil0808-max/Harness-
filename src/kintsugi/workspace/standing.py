"""Approvals the owner chose to remember: "always allow this exact action".

A scheduled task that needs approval stalls while nobody is around. The owner can approve one *exact* call (the same tool with the same
arguments, down to the last character) permanently, in the one room where it was approved. Nothing else is widened: a different argument,
another agent, another room, or a tool that could send data out or run without isolation and without a blocked network still asks. For
code, the approval also stops applying as soon as any .py file in the agent's folder changes (so code the agent rewrites later is
reviewed again). Entries are listed in Settings, can be revoked any time, and only a person's click can add one (an agent cannot)."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

MAX_PER_AGENT = 30
ALLOWED_TOOLS = {"run_python", "web_search", "web_fetch"}  # plus read-only (safe) plugin and integration tools, checked by the caller


MAX_PY_FILES = 300
MAX_PY_BYTES = 2_000_000


def fingerprint(ws: "Workspace", agent: str) -> str | None:
    """A digest of the Python files in the agent's folder (what approved code could import). None when there are too many to check."""
    root = ws.agent_dir(agent)
    digest, count, total = hashlib.sha256(), 0, 0
    for path in sorted(root.rglob("*.py")) if root.is_dir() else []:
        if path.is_symlink() or not path.is_file():
            continue
        count += 1
        total += path.stat().st_size
        if count > MAX_PY_FILES or total > MAX_PY_BYTES:
            return None
        digest.update(str(path.relative_to(root)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def call_hash(tool: str, args: dict, room: str = "", fp: str = "") -> str:
    return hashlib.sha256((tool + "\0" + json.dumps(args, sort_keys=True, ensure_ascii=False) + "\0" + room + "\0" + fp).encode()).hexdigest()


def _hash(ws: "Workspace", agent: str, tool: str, args: dict, room: str) -> str | None:
    fp = fingerprint(ws, agent) if tool == "run_python" else ""
    return None if fp is None else call_hash(tool, args, room, fp)


def _key(agent: str) -> str:
    return f"standing:{agent}"


def _load(ws: "Workspace", agent: str) -> list[dict]:
    try:
        data = json.loads(ws.get_setting(_key(agent), "") or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def rememberable(ws: "Workspace", tool: str, args: dict, read_only: bool = False) -> bool:
    """Only calls that stay inside the agent's own folder or only read: isolated code without secrets, searches, page reads, read-only tools."""
    if ws.team.owner_only_tool(tool, args):
        return False
    if tool == "run_python":
        from . import sandbox

        status = sandbox.status()
        return not args.get("secrets") and bool(status["isolated"]) and bool(status["network_blocked"])
    return tool in ALLOWED_TOOLS or read_only


def matches(ws: "Workspace", agent: str, tool: str, args: dict, room: str) -> bool:
    h = _hash(ws, agent, tool, args, room)
    return h is not None and any(e.get("h") == h for e in _load(ws, agent))


def ensure_room_for_one_more(ws: "Workspace", agent: str) -> None:
    """Checked before the call runs, so a refusal never happens after the action was already carried out."""
    from .core import WorkspaceError

    if len(_load(ws, agent)) >= MAX_PER_AGENT:
        raise WorkspaceError(f"at most {MAX_PER_AGENT} remembered approvals per agent: revoke some in Settings first")


def remember(ws: "Workspace", agent: str, tool: str, args: dict, by: str, room: str, read_only: bool = False) -> bool:
    from .core import WorkspaceError

    if not rememberable(ws, tool, args, read_only):
        raise WorkspaceError("this kind of action always asks: it could send data out, use secrets, or run without isolation")
    fp = fingerprint(ws, agent) if tool == "run_python" else ""
    if fp is None:
        raise WorkspaceError("this agent's folder has too many Python files to check, so this cannot be remembered")
    entries = _load(ws, agent)
    h = call_hash(tool, args, room, fp)
    if any(e.get("h") == h for e in entries):
        return False
    ensure_room_for_one_more(ws, agent)
    text = args.get("code") if tool == "run_python" and isinstance(args.get("code"), str) else json.dumps(args, ensure_ascii=False)
    entries.append({"h": h, "tool": tool, "room": room, "fp": fp, "summary": text[:160], "size": len(text), "by": by, "ts": ws.clock()})
    ws.set_setting(_key(agent), json.dumps(entries))
    ws.audit(agent, "approval-remembered", f"{tool} in {room} by {by}")
    return True


def listing(ws: "Workspace") -> list[dict]:
    out = []
    for row in ws.db.query("SELECT name FROM agents ORDER BY name"):
        entries = _load(ws, row["name"])
        now = fingerprint(ws, row["name"]) if any(e.get("tool") == "run_python" for e in entries) else ""
        for e in entries:
            out.append({"agent": row["name"], "h": e.get("h"), "tool": e.get("tool"), "room": e.get("room", ""), "summary": e.get("summary"),
                        "size": e.get("size", 0), "by": e.get("by"), "ts": e.get("ts"),
                        "stale": e.get("tool") == "run_python" and e.get("fp") != now})
    return out


def revoke(ws: "Workspace", agent: str, h: str) -> bool:
    entries = _load(ws, agent)
    kept = [e for e in entries if e.get("h") != h]
    if len(kept) == len(entries):
        return False
    ws.set_setting(_key(agent), json.dumps(kept))
    ws.audit(agent, "approval-revoked", h[:10])
    return True


def forget_agent(ws: "Workspace", agent: str) -> None:
    ws.db.execute("DELETE FROM settings WHERE key = ?", (_key(agent),))
