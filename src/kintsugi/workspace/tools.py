"""The tools an agent can use, with their risk class and the permission check around them.

Every tool works on the agent's own folder only (see sandbox.safe_path). `execute` is the single door:
it applies the permission tier, queues an approval when needed, runs the tool, redacts secrets from the
output and writes the audit trail.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from kintsugi.graph import ContextGraph
from kintsugi.loop import load_task, parse_files, solve
from kintsugi.memory import tokens

from . import perms
from .sandbox import (MAX_FILE_BYTES, MAX_FOLDER_BYTES, PathError, folder_size, run_python, safe_path)
from .scheduler import parse_cron

if TYPE_CHECKING:
    from .core import Workspace

APP_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
MAX_READ_CHARS = 20_000
MAX_JOBS_PER_AGENT = 10


class ToolError(Exception):
    """A tool call that failed in a way the agent can learn from (bad path, code error, ...)."""


@dataclass
class Ctx:
    ws: "Workspace"
    agent: str
    room: str
    hops: int
    situation: str  # id of the message that started this run


@dataclass
class Tool:
    name: str
    risk: str  # "safe" or "risky"
    doc: str
    run: Callable[[Ctx, dict], str]


@dataclass
class Outcome:
    status: str  # ok | error | denied | pending
    output: str
    approval_id: int | None = None


def _text(args: dict, key: str, limit: int = MAX_FILE_BYTES, required: bool = True) -> str:
    value = args.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise ToolError(f"argument '{key}' must be text")
    if len(value) > limit:
        raise ToolError(f"argument '{key}' is too long (limit {limit} characters)")
    return value


def _path(ctx: Ctx, value: str) -> Path:
    try:
        return safe_path(ctx.ws.files_dir(ctx.agent), value)
    except PathError as err:
        raise ToolError(str(err)) from None


# --- safe tools -------------------------------------------------------------

def send_message(ctx: Ctx, args: dict) -> str:
    room = args.get("room") or ctx.room
    text = _text(args, "text", 2000)
    if ctx.agent not in ctx.ws.members(room):
        raise ToolError(f"you are not a member of room '{room}'")
    ctx.ws.post(room, ctx.agent, text, hops=ctx.hops)
    return f"sent to {room}"


def read_file(ctx: Ctx, args: dict) -> str:
    path = _path(ctx, _text(args, "path", 300))
    if not path.is_file():
        raise ToolError("no such file")
    content = path.read_text(errors="replace")
    return content[:MAX_READ_CHARS] + ("\n...(truncated)" if len(content) > MAX_READ_CHARS else "")


def list_files(ctx: Ctx, args: dict) -> str:
    path = _path(ctx, _text(args, "path", 300, required=False) or ".")
    if not path.is_dir():
        raise ToolError("not a folder")
    entries = sorted(path.iterdir(), key=lambda p: p.name)
    lines = [f"{p.name}{'/' if p.is_dir() else ''}  {p.stat().st_size if p.is_file() else ''}".rstrip() for p in entries[:200]]
    return "\n".join(lines) or "(empty)"


def write_file(ctx: Ctx, args: dict) -> str:
    path = _path(ctx, _text(args, "path", 300))
    content = _text(args, "content")
    base = ctx.ws.files_dir(ctx.agent)
    if path == base.resolve() or path.is_dir():
        raise ToolError("that path is a folder")
    existing = path.stat().st_size if path.exists() else 0
    if folder_size(base) - existing + len(content.encode()) > MAX_FOLDER_BYTES:
        raise ToolError("your folder is full (5 MB limit)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return f"wrote {path.relative_to(base.resolve()).as_posix()} ({len(content)} characters)"


def remember(ctx: Ctx, args: dict) -> str:
    text = _text(args, "text", 500)
    note_id = ctx.ws.add_note(ctx.agent, text)
    return f"remembered as note {note_id}"


def search_memory(ctx: Ctx, args: dict) -> str:
    hits = ctx.ws.search_notes(ctx.agent, _text(args, "query", 300))
    return "\n".join(f"note {h['id']}: {h['text']}" for h in hits) or "nothing found"


def list_secrets(ctx: Ctx, args: dict) -> str:
    return ", ".join(ctx.ws.keychain.names(ctx.agent)) or "(none)"


def map_project(ctx: Ctx, args: dict) -> str:
    base = _path(ctx, _text(args, "path", 300, required=False) or ".")
    sources = {}
    for file in sorted(base.rglob("*.py"))[:200]:
        if file.is_file() and file.stat().st_size < 200_000:
            sources[file.relative_to(base).as_posix()] = file.read_text(errors="replace")
    if not sources:
        raise ToolError("no .py files there")
    return ContextGraph.build(sources).describe()[:3000]


# --- risky tools ------------------------------------------------------------

def run_python_tool(ctx: Ctx, args: dict) -> str:
    code = _text(args, "code")
    names = args.get("secrets") or []
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise ToolError("'secrets' must be a list of secret names")
    try:
        env = ctx.ws.keychain.env_for(ctx.agent, names)
    except KeyError as err:
        raise ToolError(str(err.args[0])) from None
    timeout = min(float(args.get("timeout", 10)), 30.0)
    ok, output = run_python(ctx.ws.files_dir(ctx.agent), code, timeout=timeout, extra_env=env)
    if not ok:
        raise ToolError(output)
    return output


def publish_app(ctx: Ctx, args: dict) -> str:
    name = _text(args, "name", 40)
    if not APP_NAME_RE.match(name):
        raise ToolError("app names are lowercase letters, digits, '-' and '_'")
    html = _text(args, "html")
    folder = ctx.ws.www_dir(ctx.agent) / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(html)
    return f"published at /apps/{ctx.agent}/{name}/"


class _RecordingModel:
    """Wraps a model and remembers its last reply (the loop does not return the fixed files)."""

    def __init__(self, model) -> None:
        self.model = model
        self.last = ""
        self.usage = model.usage

    def complete(self, messages: list[dict]) -> str:
        self.last = self.model.complete(messages)
        return self.last


def fix_code(ctx: Ctx, args: dict) -> str:
    """Run the Kintsugi loop (attempt, test, retry) on a task folder inside the agent's folder."""
    folder = _path(ctx, _text(args, "path", 300))
    if not (folder / "task.json").is_file():
        raise ToolError("that folder needs a task.json with a description, source files and test_*.py files")
    try:
        task = load_task(folder)
    except (KeyError, json.JSONDecodeError) as err:
        raise ToolError(f"bad task.json: {err}") from None
    recorder = _RecordingModel(ctx.ws.model_for(ctx.agent))
    result = solve(task, recorder, max_retries=min(int(args.get("retries", 2)), 3))
    if not result.passed:
        last = result.attempts[-1]
        raise ToolError(f"not fixed after {result.num_attempts} attempt(s): {last.error_type}: {last.output[-500:]}")
    files = parse_files(recorder.last, task, list(task.sources))
    for rel, code in files.items():
        target = safe_path(folder, rel)
        target.write_text(code)
    return f"fixed after {result.num_attempts} attempt(s); updated {', '.join(sorted(files))}"


def schedule(ctx: Ctx, args: dict) -> str:
    cron = _text(args, "cron", 100)
    prompt = _text(args, "prompt", 500)
    try:
        parse_cron(cron)
    except ValueError as err:
        raise ToolError(f"bad cron expression: {err}") from None
    if len(ctx.ws.list_jobs(ctx.agent)) >= MAX_JOBS_PER_AGENT:
        raise ToolError(f"at most {MAX_JOBS_PER_AGENT} scheduled jobs per agent")
    room = args.get("room") or ctx.room
    if ctx.agent not in ctx.ws.members(room):
        raise ToolError(f"you are not a member of room '{room}'")
    job_id = ctx.ws.add_job(ctx.agent, room, cron, prompt)
    return f"scheduled job {job_id}: '{cron}' in {room}"


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("send_message", "safe", 'send_message {"room": optional room name, "text": "..."} - post a message', send_message),
    Tool("read_file", "safe", 'read_file {"path": "notes.txt"} - read a file in your folder', read_file),
    Tool("list_files", "safe", 'list_files {"path": "."} - list a folder', list_files),
    Tool("write_file", "safe", 'write_file {"path": "a.txt", "content": "..."} - write a file in your folder', write_file),
    Tool("remember", "safe", 'remember {"text": "..."} - keep a short note for later', remember),
    Tool("search_memory", "safe", 'search_memory {"query": "..."} - find your notes', search_memory),
    Tool("list_secrets", "safe", "list_secrets {} - names of the secrets you may use (never their values)", list_secrets),
    Tool("map_project", "safe", 'map_project {"path": "."} - which functions call which in your Python files', map_project),
    Tool("run_python", "risky", 'run_python {"code": "...", "secrets": ["NAME"]} - run Python in your folder', run_python_tool),
    Tool("publish_app", "risky", 'publish_app {"name": "todo", "html": "<html>..."} - publish a small web app', publish_app),
    Tool("fix_code", "risky", 'fix_code {"path": "task-folder"} - repair code with the Kintsugi loop (needs task.json and tests)', fix_code),
    Tool("schedule", "risky", 'schedule {"cron": "0 9 * * 1-5", "prompt": "...", "room": optional} - run yourself on a schedule', schedule),
]}


def describe_tools(allowed: list[str] | None) -> str:
    return "\n".join(f"- {t.doc}" for t in TOOLS.values() if allowed is None or t.name in allowed)


def execute(ctx: Ctx, name: str, args: object, approved: bool = False) -> Outcome:
    """Apply the permission tier, then run the tool. `approved=True` skips the tier (a human said yes)."""
    spec = TOOLS.get(name)
    if spec is None:
        return Outcome("error", f"unknown tool '{name}'")
    if not isinstance(args, dict):
        return Outcome("error", "tool arguments must be a JSON object")
    agent = ctx.ws.get_agent(ctx.agent)
    decision = perms.ALLOW if approved else perms.decide(agent["tier"], spec.risk, name, agent["tools"])
    if approved and agent["tools"] is not None and name not in agent["tools"]:
        decision = perms.DENY
    if decision == perms.DENY:
        ctx.ws.audit(ctx.agent, "denied", name)
        return Outcome("denied", f"tool '{name}' is not allowed for this agent")
    if decision == perms.ASK:
        approval_id = ctx.ws.request_approval(ctx.agent, ctx.room, name, args)
        ctx.ws.audit(ctx.agent, "approval-requested", f"#{approval_id} {name}")
        return Outcome("pending", f"waiting for a human to approve (approval #{approval_id})", approval_id)
    try:
        output = spec.run(ctx, args)
        status = "ok"
    except ToolError as err:
        output, status = str(err), "error"
    except (OSError, ValueError, TypeError, KeyError) as err:
        output, status = f"{type(err).__name__}: {err}", "error"
    output = ctx.ws.keychain.redact(ctx.agent, output)
    ctx.ws.audit(ctx.agent, f"tool-{status}", f"{name} {json.dumps(args)[:200]}")
    return Outcome(status, output)
