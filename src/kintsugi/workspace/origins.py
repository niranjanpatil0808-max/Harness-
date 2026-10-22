"""Which chat a file was made in.

An agent has one folder, shared by every chat it is in. A file it writes during someone's private chat should not be readable from a team room
(a teammate could just ask the agent to read it). This keeps a small label per file, outside the folder the agent's code can touch:
files made in a private chat belong to that chat; files made in a shared room, or rewritten there, belong to the folder as before.

What this does NOT do: code the agent runs (run_python) can open any file in its folder, so approved code can still read such a file. Approvals
show the code, and docs/TEAMS.md says so."""
from __future__ import annotations

import json
import threading
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

_lock = threading.Lock()


def _file(ws: "Workspace", agent: str):
    return ws.agent_dir(agent) / "origins.json"


def _load(ws: "Workspace", agent: str) -> dict:
    try:
        data = json.loads(_file(ws, agent).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(ws: "Workspace", agent: str, data: dict) -> None:
    target = _file(ws, agent)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(target)


def _norm(relative: str) -> str:
    return str(PurePosixPath(relative.replace("\\", "/").lstrip("./")))


def mark(ws: "Workspace", agent: str, room: str, relatives: list[str]) -> None:
    """Record where these files were just written."""
    if not relatives:
        return
    private = ws.db.one("SELECT kind FROM rooms WHERE name = ?", (room,))
    private = bool(private and private["kind"] == "dm")
    with _lock:
        data = _load(ws, agent)
        before = dict(data)
        for rel in relatives:
            rel = _norm(rel)
            if private:
                data[rel] = room
            else:
                data.pop(rel, None)
        if data != before:
            _save(ws, agent, data)


def owner_room(ws: "Workspace", agent: str, relative: str) -> str | None:
    """The private chat this file belongs to, or None if it is the folder's own."""
    room = _load(ws, agent).get(_norm(relative))
    if room and ws.db.one("SELECT 1 FROM rooms WHERE name = ?", (room,)):
        return room
    return None


def allowed(ws: "Workspace", agent: str, room: str, relative: str) -> bool:
    owner = owner_room(ws, agent, relative)
    return owner is None or owner == room


def forget_room(ws: "Workspace", room: str) -> None:
    with _lock:
        for row in ws.db.query("SELECT name FROM agents"):
            data = _load(ws, row["name"])
            kept = {k: v for k, v in data.items() if v != room}
            if kept != data:
                _save(ws, row["name"], kept)
