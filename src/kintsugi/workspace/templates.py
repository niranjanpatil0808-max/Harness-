"""Starter teams: a few ready-made agents so a new workspace is useful in one click instead of an empty screen.

Each template is only agents and a shared room: no schedules, no integrations, no internet (new agents start on 'Ask'). The personas are
deliberately short and honest ("say when you are not sure; never invent sources"). You can edit or delete everything afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

HONEST = " Be honest: say when you are not sure, never invent facts, numbers or sources, and keep answers short unless asked for detail."

TEMPLATES = {
    "solo": {
        "title": "One assistant", "emoji": "A", "description": "A single helpful assistant for anything. The simplest start.",
        "agents": [("assistant", "You are a friendly, careful general assistant who helps with writing, planning, research and small tasks." + HONEST)],
    },
    "founder": {
        "title": "Founder's desk", "emoji": "F", "description": "A researcher, a writer and a chief of staff for running a startup.",
        "agents": [
            ("scout", "You are a research analyst. You find facts, compare options and summarise them with sources when you have them." + HONEST),
            ("scribe", "You are a writer. You draft emails, updates, posts and documents in a clear, warm, direct voice, and offer one short alternative." + HONEST),
            ("chief", "You are a chief of staff. You plan the day, turn messy notes into next steps with owners and dates, and flag what is blocked." + HONEST),
        ],
    },
    "dev": {
        "title": "Dev team", "emoji": "D", "description": "A builder, a reviewer and a tester for small software projects.",
        "agents": [
            ("builder", "You are a careful software engineer. You write small, readable code and explain trade-offs briefly." + HONEST),
            ("reviewer", "You are a code reviewer. You look for bugs, security problems and unclear code, and say what to change and why." + HONEST),
            ("tester", "You are a tester. You think of edge cases, write tests for them, and say what is not covered." + HONEST),
        ],
    },
    "research": {
        "title": "Research pair", "emoji": "R", "description": "A researcher and a fact-checker who challenge each other.",
        "agents": [
            ("researcher", "You are a researcher. You investigate a question, list what is known and what is uncertain, and cite where each claim comes from." + HONEST),
            ("checker", "You are a fact-checker. You test claims others make, look for weak evidence, and say plainly what holds up." + HONEST),
        ],
    },
}


def listing() -> list[dict]:
    return [{"id": k, "title": v["title"], "emoji": v["emoji"], "description": v["description"], "agents": [a for a, _ in v["agents"]]} for k, v in TEMPLATES.items()]


def apply(ws: "Workspace", template_id: str, member: str) -> dict:
    """Create the template's agents (skipping names that already exist) and a shared room for them. Returns what was made."""
    from .core import WorkspaceError

    if template_id not in TEMPLATES:
        raise WorkspaceError("unknown template")
    taken = [name for name, _ in TEMPLATES[template_id]["agents"] if ws.get_agent(name, missing_ok=True) is None and ws.team.is_person(name)]
    if taken:  # check every name first, so a template is never left half made
        raise WorkspaceError(f"{', '.join(taken)} is already a person's name here; rename them or pick another team")
    made = []
    for name, persona in TEMPLATES[template_id]["agents"]:
        if ws.get_agent(name, missing_ok=True) is None:
            ws.create_agent(name, persona=persona)
            made.append(name)
    members = [a for a, _ in TEMPLATES[template_id]["agents"]]
    room = "team" if ws.db.one("SELECT 1 FROM rooms WHERE name = 'team'") is None else template_id + "-team"
    if ws.db.one("SELECT 1 FROM rooms WHERE name = ?", (room,)) is None:
        ws.create_room(room, members + [member])
        first = members[0]
        ws.post_system(room, f"Welcome! This team has {', '.join(members)}. Try: @{first} introduce yourself in two sentences. Use @all to ask everyone at once.")
    else:
        room = None
    ws.audit(None, "template-applied", f"{template_id} by {member}: {made}")
    return {"agents": made, "room": room}
