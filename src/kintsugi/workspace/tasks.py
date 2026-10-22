"""The team task board: hand work to an agent in a shared room, and let everyone in that room follow it.

A task is an ordinary message ("@agent Task #7: ...") plus a row that tracks it: queued, working, waiting (for an
approval), done, stopped or failed. The board shows only tasks from rooms the viewer is in (the owner sees all).
Nothing here gives anyone more power: the agent runs with the same rules and approvals as for any message."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace
    from .team import Identity

MAX_TITLE = 600
MAX_OPEN_PER_ROOM = 200
OPEN = ("queued", "working", "waiting")
STATUSES = OPEN + ("done", "stopped", "failed")
_RESUME = re.compile(r"\(approval #(\d+)\)")
_TASK = re.compile(r"^@([a-z0-9_-]+) Task #(\d+)[ :(]")

class TaskError(ValueError):
    pass


def create(ws: "Workspace", who: "Identity", sender: str, room: str, agent: str, title: str) -> dict:
    title = " ".join(str(title).split())[:MAX_TITLE]
    if not title:
        raise TaskError("say what the agent should do")
    if not ws.team.can_see_room(who, room) or sender not in ws.members(room):
        raise TaskError("you can only give tasks in rooms you belong to")
    if ws.get_agent(agent, missing_ok=True) is None or agent not in ws.members(room):
        raise TaskError(f"{agent} is not in this room")
    if ws.db.one("SELECT COUNT(*) AS n FROM tasks WHERE room = ? AND status IN ('queued','working','waiting')", (room,))["n"] >= MAX_OPEN_PER_ROOM:
        raise TaskError("this room has too many open tasks; finish or remove some first")
    now = ws.clock()
    task_id = ws.db.execute("INSERT INTO tasks (room, agent, title, created_by, status, created, updated) VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                            (room, agent, title, sender, now, now))
    message_id = ws.post(room, sender, f"@{agent} Task #{task_id}: {title}", human=True)
    # the agent may already have claimed this message (a synchronous workspace runs it inside post())
    ws.db.execute("UPDATE tasks SET message_id = ? WHERE id = ? AND message_id IS NULL", (message_id, task_id))
    ws.audit(None, "task-created", f"#{task_id} {agent} in {room} by {sender}")
    return get(ws, task_id)


def get(ws: "Workspace", task_id: int) -> dict:
    row = ws.db.one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
    if row is None:
        raise TaskError("no such task")
    return dict(row)


def listing(ws: "Workspace", who: "Identity", room: str | None = None, limit: int = 200) -> list[dict]:
    rows = ws.db.query("SELECT * FROM tasks ORDER BY CASE WHEN status IN ('queued','working','waiting') THEN 0 ELSE 1 END, updated DESC LIMIT 2000")
    visible = {}
    out = []
    for r in rows:
        if room and r["room"] != room:
            continue
        if r["room"] not in visible:
            visible[r["room"]] = ws.team.can_see_room(who, r["room"])
        if visible[r["room"]]:
            out.append(dict(r))
        if len(out) >= limit:
            break
    return out


def open_counts(ws: "Workspace", who: "Identity") -> int:
    return sum(1 for t in listing(ws, who) if t["status"] in OPEN)


def _task_for_message(ws: "Workspace", message_id: int) -> dict | None:
    row = ws.db.one("SELECT * FROM tasks WHERE message_id = ?", (message_id,))
    if row is not None:
        return row
    msg = ws.db.one("SELECT text, sender, room FROM messages WHERE id = ?", (message_id,))
    if msg is None:
        return None
    t = _TASK.match(msg["text"])
    if t and msg["sender"] != "system":  # the task's own message, before create() recorded its id
        row = ws.db.one("SELECT * FROM tasks WHERE id = ? AND created_by = ? AND room = ? AND agent = ? AND message_id IS NULL",
                        (int(t.group(2)), msg["sender"], msg["room"], t.group(1)))
        if row is not None:
            ws.db.execute("UPDATE tasks SET message_id = ? WHERE id = ?", (message_id, row["id"]))
            return ws.db.one("SELECT * FROM tasks WHERE id = ?", (row["id"],))
        return None
    if msg["sender"] != "system":
        return None
    m = _RESUME.search(msg["text"])  # the agent was woken again after an approval: it is the same task
    if not m:
        return None
    row = ws.db.one("SELECT * FROM tasks WHERE approval_id = ? AND status = 'waiting'", (int(m.group(1)),))
    if row is not None:
        ws.db.execute("UPDATE tasks SET message_id = ? WHERE id = ?", (message_id, row["id"]))
    return row


def started(ws: "Workspace", agent: str, message_id: int) -> None:
    task = _task_for_message(ws, message_id)
    if task is not None and task["agent"] == agent and task["status"] in OPEN:
        ws.db.execute("UPDATE tasks SET status = 'working', updated = ? WHERE id = ?", (ws.clock(), task["id"]))


def finish(ws: "Workspace", agent: str, room: str, message_id: int, outcome: str, stopped: bool) -> None:
    """Called when an agent run ends. outcome is 'ran' or 'failed'."""
    task = ws.db.one("SELECT * FROM tasks WHERE message_id = ?", (message_id,))
    if task is None or task["agent"] != agent or task["status"] not in OPEN:
        return
    now = ws.clock()
    pending = ws.db.one("SELECT id FROM approvals WHERE agent = ? AND room = ? AND status = 'pending' AND id > COALESCE(?, 0) ORDER BY id DESC LIMIT 1",
                        (agent, room, task["approval_id"]))
    reply = ws.db.one("SELECT MAX(id) AS id FROM messages WHERE room = ? AND sender = ? AND id > ?", (room, agent, message_id))["id"]
    if outcome == "failed":
        status = "failed"
    elif stopped:
        status = "stopped"
    elif pending is not None:
        ws.db.execute("UPDATE tasks SET status = 'waiting', approval_id = ?, result_id = COALESCE(?, result_id), updated = ? WHERE id = ?",
                      (pending["id"], reply, now, task["id"]))
        return
    else:
        status = "done"
    ws.db.execute("UPDATE tasks SET status = ?, result_id = COALESCE(?, result_id), updated = ? WHERE id = ?", (status, reply, now, task["id"]))
    if status in ("done", "failed"):
        ws.notify_if_away("task", [task["created_by"]] if ws.team.is_person(task["created_by"]) else None)


def update(ws: "Workspace", who: "Identity", sender: str, task_id: int, action: str) -> dict | None:
    task = get(ws, task_id)
    if not ws.team.can_see_room(who, task["room"]):
        raise TaskError("no such task")
    if task["created_by"] != sender and not who.at_least("admin"):
        raise TaskError("only the person who gave the task, or an admin, can change it")
    now = ws.clock()
    if action == "done":
        ws.db.execute("UPDATE tasks SET status = 'done', updated = ? WHERE id = ?", (now, task["id"]))
    elif action == "delete":
        ws.db.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        return None
    elif action == "retry":
        if task["status"] in ("queued", "working"):
            raise TaskError("the agent is still on it")
        if sender not in ws.members(task["room"]) or task["agent"] not in ws.members(task["room"]):
            raise TaskError("you or the agent are no longer in that room")
        ws.db.execute("UPDATE tasks SET status = 'queued', message_id = NULL, approval_id = NULL, updated = ? WHERE id = ?", (now, task["id"]))
        message_id = ws.post(task["room"], sender, f"@{task['agent']} Task #{task['id']} (again): {task['title']}", human=True)
        ws.db.execute("UPDATE tasks SET message_id = ? WHERE id = ? AND message_id IS NULL", (message_id, task["id"]))
    else:
        raise TaskError("unknown action")
    return get(ws, task["id"])


def forget_room(ws: "Workspace", room: str) -> None:
    ws.db.execute("DELETE FROM tasks WHERE room = ?", (room,))


def forget_agent(ws: "Workspace", agent: str) -> None:
    ws.db.execute("DELETE FROM tasks WHERE agent = ?", (agent,))
