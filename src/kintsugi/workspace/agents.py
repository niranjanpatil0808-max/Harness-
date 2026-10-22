"""The agent runtime: read the room, ask the model, run tools, answer, and learn from tool mistakes.

An agent's lessons live in its own `lessons.json`, handled by `kintsugi.memory.MemoryStore` (the same
mistake memory the benchmark uses): a failed tool call is turned into a short general lesson, shown on the
next step and on later runs, kept when runs that used it succeed and dropped when it never helps.

The model is told to call tools by writing fenced ```tool blocks of JSON, so any chat model works and no
tool-calling API is needed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from kintsugi.memory import MemoryStore, tokens

from .tools import TOOLS, Ctx, describe_tools, execute

if TYPE_CHECKING:
    from .core import Workspace

MAX_STEPS = 6
MAX_TOOLS_PER_STEP = 3
HISTORY_MESSAGES = 12
FENCE_RE = re.compile(r"```([a-zA-Z]*)[ \t]*\n(.*?)```", re.S)

SYSTEM = """You are {name}, an AI assistant in a shared workspace. {persona}
You work in rooms with people and other agents. Be brief and useful.

To use a tool, reply with a block like this, INCLUDING the three backticks (at most {max_tools} blocks per reply):
```tool
{{"tool": "write_file", "args": {{"path": "notes.txt", "content": "hello"}}}}
```
You will then see the results and can continue. When you are finished, reply with plain text and NO tool
block: that text is posted to the room (reply DONE if you already said everything with send_message).
Use only the tools below. Never print, guess or repeat secrets.
Tools:
{tools}"""


TOOL_REFLECT_PROMPT = """One of your tool calls just failed.

Request you were handling: {request}

Failed call and error:
```
{output}
```

Write ONE short, general lesson (max 2 sentences) that would help you avoid this kind of mistake on OTHER
requests. Do not mention file names or values from this request. Start with "When". Reply with the lesson only."""


class AgentMemory(MemoryStore):
    """The benchmark's MemoryStore, with a reflection prompt that fits tool calls instead of bug fixes."""

    def reflect(self, model, task, files, result):
        reply = model.complete([{"role": "user", "content": TOOL_REFLECT_PROMPT.format(
            request=task.description[:500], output=result.output[-1000:])}])
        text = reply.strip().strip('"').strip()
        if len(text) < 15:
            return None
        return self.add(text, result.error_type, tokens(task.description), task.id)


@dataclass
class Situation:
    """Duck-types kintsugi.loop.Task, so the benchmark's MemoryStore can be reused unchanged."""

    id: str
    description: str
    sources: dict = field(default_factory=dict)


@dataclass
class Failure:
    """Duck-types kintsugi.verifier.VerifyResult for MemoryStore.reflect."""

    error_type: str
    output: str


def parse_reply(reply: str) -> tuple[list[dict], str]:
    """Split a model reply into tool calls and the plain text around them."""
    calls: list[dict] = []

    def take(match: re.Match) -> str:
        label, body = match.group(1).lower(), match.group(2).strip()
        if label not in ("tool", "json", ""):
            return match.group(0)  # a code example, not a tool call
        try:
            data = json.loads(body)
        except json.JSONDecodeError as err:
            if label == "tool":
                calls.append({"_error": f"could not read the tool block as JSON ({err.msg})"})
                return ""
            return match.group(0)
        if isinstance(data, dict) and isinstance(data.get("tool"), str):
            calls.append({"tool": data["tool"], "args": data.get("args", {})})
            return ""
        if label == "tool":
            calls.append({"_error": 'a tool block must look like {"tool": "name", "args": {...}}'})
            return ""
        return match.group(0)

    plain = FENCE_RE.sub(take, reply)
    plain = _take_unfenced(plain, calls)
    return calls, plain.strip()


UNFENCED_RE = re.compile(r"^[ \t]*(?:tool[ \t]*:[ \t]*)?([a-z_]+)[ \t]*[(:]?[ \t]*(?=\{)", re.M)
BARE_RE = re.compile(r"^[ \t]*(?=\{)", re.M)
FENCED_SPAN_RE = re.compile(r"(```.*?```)", re.S)


def _take_unfenced(text: str, calls: list[dict]) -> str:
    """Small models often skip the code fence and write `write_file {"path": ...}` or a bare tool JSON line.
    Accept those, but only outside code blocks and only for tool names that exist."""
    decoder = json.JSONDecoder()
    out = []
    for index, piece in enumerate(FENCED_SPAN_RE.split(text)):
        if index % 2:  # a code block that was not a tool call: leave it alone
            out.append(piece)
            continue
        position, kept = 0, []
        while True:
            named = UNFENCED_RE.search(piece, position)
            bare = BARE_RE.search(piece, position)
            match = min((m for m in (named, bare) if m), key=lambda m: m.start(), default=None)
            if match is None:
                break
            try:
                data, end = decoder.raw_decode(piece, match.end())
            except json.JSONDecodeError:
                kept.append(piece[position:match.end()])
                position = match.end()
                continue
            name = match.group(1) if match is named else None  # None: a bare {"tool": ...} object
            if name is not None and name in TOOLS and isinstance(data, dict):
                calls.append({"tool": name, "args": data})
            elif name is None and isinstance(data, dict) and isinstance(data.get("tool"), str):
                calls.append({"tool": data["tool"], "args": data.get("args", {})})
            else:
                kept.append(piece[position:end])
                position = end
                continue
            kept.append(piece[position:match.start()])
            position = end
        kept.append(piece[position:])
        out.append("".join(kept))
    return "".join(out)


def build_context(ws: "Workspace", room: str, message_id: int, lessons_text: str, notes: list[dict]) -> str:
    history = ws.history(room, limit=HISTORY_MESSAGES)
    parts = [f"Room: {room} (members: {', '.join(ws.members(room))})"]
    if lessons_text:
        parts.append(lessons_text)
    if notes:
        parts.append("Your notes:\n" + "\n".join(f"- {n['text']}" for n in notes))
    parts.append("Recent messages:\n" + "\n".join(f"[{m['id']}] {m['sender']}: {m['text']}" for m in history))
    parts.append(f"Respond to the message addressed to you (message {message_id}).")
    return "\n\n".join(parts)


def run_agent(ws: "Workspace", name: str, room: str, message_id: int, hops: int) -> None:
    agent = ws.get_agent(name)
    trigger = ws.db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
    situation = Situation(id=f"{room}#{message_id}", description=trigger["text"])
    memory = AgentMemory.load(ws.lessons_path(name))
    lessons = memory.retrieve(situation)
    shown = [lesson.id for lesson in lessons]
    model = ws.model_for(name)
    ctx = Ctx(ws, name, room, hops, situation.id)

    system = SYSTEM.format(name=name, persona=agent["persona"], max_tools=MAX_TOOLS_PER_STEP,
                           tools=describe_tools(agent["tools"]))
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": build_context(ws, room, message_id, memory.format(lessons),
                                                  ws.search_notes(name, trigger["text"], limit=3))},
    ]
    try:
        _loop(ws, name, room, hops, model, ctx, memory, situation, messages, shown)
    finally:
        memory.save()  # a lesson learned just before a model outage is still kept


def _loop(ws, name, room, hops, model, ctx, memory, situation, messages, shown) -> None:
    finished = False
    waiting = False
    last_step_failed = False
    reflected = False
    for _ in range(MAX_STEPS):
        reply = model.complete(messages)
        calls, plain = parse_reply(reply)
        if not calls:
            finished = True
            if plain and plain.upper() != "DONE":
                ws.post(room, name, plain, hops=hops)
            break

        results, failures = [], []
        for call in calls[:MAX_TOOLS_PER_STEP]:
            if "_error" in call:
                results.append(f"[tool block] error: {call['_error']}")
                failures.append(("format", None))
                continue
            outcome = execute(ctx, call["tool"], call["args"])
            results.append(f"[{call['tool']}] {outcome.status}: {outcome.output}")
            if outcome.status == "pending":
                waiting = True
                ws.post(room, name, f"I need approval to run {call['tool']} (approval #{outcome.approval_id}).", hops=hops)
            elif outcome.status != "ok":
                failures.append((outcome.status, f"{call['tool']}: {outcome.output}"))
        if waiting:
            break
        feedback = "Tool results:\n" + "\n".join(results)
        real_errors = [text for kind, text in failures if kind == "error"]
        if real_errors and not reflected:
            reflected = True  # one reflection per run keeps the cost bounded
            lesson = memory.reflect(model, situation, {}, Failure("ToolError", real_errors[0]))
            if lesson:
                feedback += f"\nLesson from this failure: {lesson.text}"
                shown.append(lesson.id)
        last_step_failed = bool(failures)
        messages = messages + [{"role": "assistant", "content": reply}, {"role": "user", "content": feedback}]
    else:
        ws.post(room, name, f"(I stopped after {MAX_STEPS} steps without finishing.)", hops=hops)

    if not waiting:  # a run that is waiting for a human has no outcome yet
        memory.record_outcome(shown, finished and not last_step_failed, situation.id)
