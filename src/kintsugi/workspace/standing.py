"""Approvals the owner chose to remember: "always allow this exact action".

A scheduled task that needs approval stalls while nobody is around. The owner can approve one *exact* call (the same tool with the same
arguments, down to the last character) permanently. Nothing else is widened: a different argument, another agent, or a tool that could
send data out or run without isolation still asks. Entries are listed in Settings, can be revoked any time, and only a person's click
can add one (an agent cannot)."""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

MAX_PER_AGENT = 30
ALLOWED_TOOLS = {"run_python", "web_search", "web_fetch"}  # plus read-only (safe) plugin and integration tools, checked by the caller


def call_hash(tool: str, args: dict) -> str:
    return hashlib.sha256((tool + "\0" + json.dumps(args, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


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
        return not args.get("secrets")
    return tool in ALLOWED_TOOLS or read_only


def matches(ws: "Workspace", agent: str, tool: str, args: dict) -> bool:
    h = call_hash(tool, args)
    return any(e.get("h") == h for e in _load(ws, agent))


def remember(ws: "Workspace", agent: str, tool: str, args: dict, by: str, read_only: bool = False) -> bool:
    from .core import WorkspaceError

    if not rememberable(ws, tool, args, read_only):
        raise WorkspaceError("this kind of action always asks: it could send data out, use secrets, or run without isolation")
    entries = _load(ws, agent)
    h = call_hash(tool, args)
    if any(e.get("h") == h for e in entries):
        return False
    if len(entries) >= MAX_PER_AGENT:
        raise WorkspaceError(f"at most {MAX_PER_AGENT} remembered approvals per agent: revoke some in Settings first")
    summary = (args.get("code") if tool == "run_python" and isinstance(args.get("code"), str) else json.dumps(args, ensure_ascii=False))[:160]
    entries.append({"h": h, "tool": tool, "summary": summary, "by": by, "ts": ws.clock()})
    ws.set_setting(_key(agent), json.dumps(entries))
    ws.audit(agent, "approval-remembered", f"{tool} by {by}")
    return True


def listing(ws: "Workspace") -> list[dict]:
    out = []
    for row in ws.db.query("SELECT name FROM agents ORDER BY name"):
        for e in _load(ws, row["name"]):
            out.append({"agent": row["name"], "h": e.get("h"), "tool": e.get("tool"), "summary": e.get("summary"), "by": e.get("by"), "ts": e.get("ts")})
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
