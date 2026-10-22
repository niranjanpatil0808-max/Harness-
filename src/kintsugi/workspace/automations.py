"""Ready-made automations: a daily briefing, a change monitor and a research report.

Each one is just a scheduled message to an agent (a job), built from a template so a phone user only picks a time and a
topic. The prompts tell the agent to use web search and its notes, to cite sources, and (for monitors) to stay silent when
nothing important is new. Nothing here can do more than the agent could already do when you message it yourself, and
anything risky still waits for your approval.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from .scheduler import cron_next, parse_cron

if TYPE_CHECKING:
    from .core import Workspace

KINDS = ("briefing", "monitor", "report", "custom")
MAX_AUTOMATIONS = 30
MAX_TOPICS, MAX_TOPIC_CHARS = 5, 80
DAYS = {"daily": "*", "weekdays": "1-5", "weekends": "0,6", "mon": "1", "tue": "2", "wed": "3", "thu": "4", "fri": "5", "sat": "6", "sun": "0"}
DAY_NAMES = {"*": "Every day", "1-5": "Every weekday", "0,6": "Every weekend", "1": "Every Monday", "2": "Every Tuesday", "3": "Every Wednesday",
             "4": "Every Thursday", "5": "Every Friday", "6": "Every Saturday", "0": "Every Sunday"}


def _line(text: object, limit: int) -> str:
    """One printable line: no control characters, no backticks, no newlines (a topic must not be able to reshape a prompt)."""
    text = re.sub(r"[\x00-\x1f\x7f`]", " ", str(text or ""))
    return " ".join(text.split())[:limit].strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "item"


def to_cron(when: dict) -> str:
    """{"time": "08:00", "days": "weekdays"} -> a cron expression in the owner's time zone."""
    match = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(when.get("time", "")).strip())
    if not match:
        raise ValueError("the time must look like 08:30")
    days = str(when.get("days", "daily")).lower()
    if days in DAYS:
        day_field = DAYS[days]
    elif re.fullmatch(r"[0-6](,[0-6]){0,6}", days):
        day_field = days
    else:
        raise ValueError("days must be daily, weekdays, weekends, a weekday name like mon, or digits like 1,3,5")
    return f"{int(match.group(2))} {int(match.group(1))} * * {day_field}"


def describe_schedule(cron: str) -> str:
    parts = cron.split()
    if len(parts) == 5 and parts[0].isdigit() and parts[1].isdigit() and parts[2] == "*" and parts[3] == "*" and parts[4] in DAY_NAMES:
        return f"{DAY_NAMES[parts[4]]} at {int(parts[1]):02d}:{int(parts[0]):02d}"
    return f"On schedule {cron}"


def build(kind: str, params: dict) -> tuple[str, str]:
    """(title, prompt) for a template."""
    if kind == "briefing":
        raw = params.get("topics") or []
        topics = [t for t in (_line(x, MAX_TOPIC_CHARS) for x in (raw if isinstance(raw, list) else str(raw).split(","))) if t][:MAX_TOPICS]
        if not topics:
            raise ValueError("add at least one topic for the briefing")
        return "Daily briefing", (
            "Write my briefing. For each topic below, use web_search to find the most important recent news and give one or two lines "
            "with the source URL. Then, from your notes, add anything I should remember today. Keep the whole briefing under 200 words "
            "and put the most important item first. Topics: " + "; ".join(topics))
    if kind == "monitor":
        query = _line(params.get("query"), 120)
        if len(query) < 3:
            raise ValueError("say what to watch for")
        slug = _slug(query)
        return f"Watch: {query}", (
            f"Monitor task. Use web_search for: {query}. Compare what you find with your note that starts with 'monitor:{slug}'. "
            "If there is something genuinely new and important since that note, send a short alert (two sentences at most) with the "
            f"source URL, then use remember to save a note starting 'monitor:{slug}' that summarises the latest state. "
            "If nothing important is new, reply with exactly DONE and nothing else.")
    if kind == "report":
        topic = _line(params.get("topic"), 150)
        if len(topic) < 3:
            raise ValueError("say what to research")
        return f"Report: {topic}", (
            f"Research this and write a short report (at most 300 words, ending with a Sources list of URLs): {topic}. "
            f"Use web_search a few times. Save the report with write_file as reports/{_slug(topic)}.md, then post a three-sentence summary here.")
    if kind == "custom":
        prompt = _line(params.get("prompt"), 500)
        if len(prompt) < 5:
            raise ValueError("write what the agent should do")
        return _line(params.get("title") or prompt, 60), prompt
    raise ValueError("kind must be one of: " + ", ".join(KINDS))


def create(ws: "Workspace", kind: str, agent: str, room: str, params: dict, when: dict | None = None, owner: str = "you") -> dict:
    """Create an automation. A report with no schedule runs once, right now. Returns {"id", "warning", ...}."""
    from .core import WorkspaceError

    try:
        title, prompt = build(kind, params)
        cron = to_cron(when) if when else None
        if cron:
            parse_cron(cron)
    except ValueError as err:
        raise WorkspaceError(str(err)) from None
    ws.get_agent(agent)
    if agent not in ws.members(room):
        raise WorkspaceError(f"{agent} is not in that room")
    if kind != "report" and not cron:
        raise WorkspaceError("pick a time for this automation")
    if cron and len(ws.list_jobs()) >= MAX_AUTOMATIONS:
        raise WorkspaceError(f"at most {MAX_AUTOMATIONS} automations")
    warning = ""
    if kind in ("briefing", "monitor", "report") and not ws.search_settings()["configured"]:
        warning = "Web search is off, so this can only use the agent's notes. Add a search key in Settings > Search."
    if not cron:  # a one-off report: post it now
        message = ws.post(room, owner, f"@{agent} {prompt}", human=True)
        return {"id": None, "message": message, "warning": warning, "title": title}
    job = ws.add_job(agent, room, cron, prompt, kind=kind, title=title, owner=owner)
    ws.audit(agent, "automation-created", f"#{job} {kind}: {title}")
    return {"id": job, "warning": warning, "title": title}


def listing(ws: "Workspace", now: float | None = None) -> list[dict]:
    """Every automation with a readable schedule and the next time it will run (in the owner's time zone)."""
    now = ws.clock() if now is None else now
    local: datetime = ws.local_datetime(now)
    out = []
    for job in ws.list_jobs():
        try:
            nxt = cron_next(job["cron"], local) if job["enabled"] else None
        except ValueError:
            nxt = None
        out.append({**job, "schedule": describe_schedule(job["cron"]), "next_run_ts": nxt.timestamp() if nxt else None})
    return out
