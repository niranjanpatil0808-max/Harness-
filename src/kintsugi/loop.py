"""Attempt, verify, retry.

The model gets the task, answers with whole files in fenced code blocks, the
verifier runs the tests, and on failure the trimmed error goes back to the
model for another try. Memory and the context graph plug in as optional
helpers, so the same loop runs every benchmark mode.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .graph import ContextGraph
from .model import Model, ModelInfraError, ModelRequestError
from .verifier import VerifyResult, verify

if TYPE_CHECKING:
    from .memory import MemoryStore

SYSTEM_PROMPT = """You fix bugs in small Python projects.
Rules:
- Do not change the tests. Make the tests pass by fixing the source files.
- Reply with every file you change, complete, in its own fenced block:
```python
# file: path/to/file.py
<full file contents>
```
- No explanations outside the code blocks are needed."""

# A fenced block, optionally tagged with "# file: name" on its first line
# (or "```python name.py" on the fence itself).
BLOCK_RE = re.compile(r"```[a-zA-Z]*[ \t]*([\w./-]+\.py)?[ \t]*\n(.*?)```", re.S)
FILE_TAG_RE = re.compile(r"^\s*#\s*file:\s*([\w./-]+\.py)\s*\n")


@dataclass
class Task:
    id: str
    dir: Path
    description: str
    sources: dict[str, str]  # relative path -> code the model may change
    tests: dict[str, str]  # relative path -> test code (read-only)
    meta: dict = field(default_factory=dict)


def load_task(task_dir: Path) -> Task:
    task_dir = Path(task_dir)
    meta = json.loads((task_dir / "task.json").read_text())
    sources, tests = {}, {}
    for path in sorted(task_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(task_dir).as_posix()
        (tests if path.name.startswith("test_") else sources)[rel] = path.read_text()
    return Task(meta.get("id", task_dir.name), task_dir, meta["description"], sources, tests, meta)


def parse_files(reply: str, task: Task, editable: list[str] | None = None) -> dict[str, str]:
    """Extract {path: code} from the model reply, ignoring edits to tests or files it wasn't shown."""
    editable = list(task.sources) if editable is None else editable
    files: dict[str, str] = {}
    for fence_name, body in BLOCK_RE.findall(reply):
        name = fence_name
        tag = FILE_TAG_RE.match(body)
        if tag:
            name = tag.group(1)
            body = body[tag.end():]
        if not name and len(editable) == 1:
            name = editable[0]  # untagged block, only one file it can be
        name = name.removeprefix("./") if name else name
        if name in editable:
            files[name] = body.rstrip() + "\n"
    return files or parse_unfenced(reply, editable)


# Some small models write "# file: x.py" and the code but leave out the opening ``` fence.
FILE_LINE_RE = re.compile(r"^[ \t]*#\s*file:\s*([\w./-]+\.py)[ \t]*$", re.M)


def parse_unfenced(reply: str, editable: list[str]) -> dict[str, str]:
    """Fallback for replies with no fenced blocks: sections that start with a '# file: path' line.

    A section ends at the next '# file:' line or at a stray closing ``` fence.
    """
    marks = list(FILE_LINE_RE.finditer(reply))
    files: dict[str, str] = {}
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(reply)
        body = reply[mark.end():end].split("```", 1)[0]
        name = mark.group(1).removeprefix("./")
        if name in editable and body.strip():
            files[name] = body.strip("\n").rstrip() + "\n"
    return files


def format_files(files: dict[str, str]) -> str:
    return "\n\n".join(f"```python\n# file: {path}\n{code.rstrip()}\n```" for path, code in files.items())


@dataclass
class Attempt:
    number: int
    passed: bool
    error_type: str
    output: str
    files_changed: list[str]
    lessons_used: list[str] = field(default_factory=list)
    reply: str = ""  # start of the model's raw reply, kept for failed attempts so failures can be inspected


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    attempts: list[Attempt]
    lessons_learned: list[str] = field(default_factory=list)

    @property
    def num_attempts(self) -> int:
        return len(self.attempts)

    @property
    def errored(self) -> bool:
        """True if the task ended on an infrastructure error: it says nothing about the model."""
        return bool(self.attempts) and self.attempts[-1].error_type == "ApiError"


def build_prompt(task: Task, use_graph: bool, lessons_text: str) -> tuple[str, list[str]]:
    """Return the first user prompt and the files the model is allowed to edit."""
    if use_graph:
        code, editable = ContextGraph.build(task.sources).context_for(task)
    else:
        code, editable = format_files(task.sources), list(task.sources)
    parts = [f"Task: {task.description}"]
    if lessons_text:
        parts.append(lessons_text)
    parts.append(f"Source files:\n{code}")
    parts.append(f"Tests (do not edit):\n{format_files(task.tests)}")
    parts.append("Return the fixed source file(s).")
    return "\n\n".join(parts), editable


def headline(output: str) -> str:
    """One line describing a test failure: the last exception line, else the first line."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if re.match(r"^[\w.]*(Error|Exception|Failure)\b", line):
            return line[:160]
    return (lines[0] if lines else "no output")[:160]


def repeat_warning(files: dict[str, str], task: Task, earlier: list[dict[str, str]]) -> str:
    """Tell the model when it handed back code it has already tried (or the original, unchanged)."""
    if files and all(files[path].strip() == task.sources.get(path, "").strip() for path in files):
        return "You returned the original code unchanged, so nothing is fixed. Change the code.\n"
    for number, previous in enumerate(earlier, 1):
        if files and files == previous:
            return (f"This is identical to your attempt {number}, which failed the same way. "
                    "Do not repeat it: find a different cause.\n")
    return ""


def solve(
    task: Task,
    model: Model,
    max_retries: int = 3,
    memory: "MemoryStore | None" = None,
    use_graph: bool = False,
    learn: bool = True,
    timeout: float = 10.0,
) -> TaskResult:
    """Run one task through the loop. `max_retries=0` is the plain single-shot baseline."""
    lessons = memory.retrieve(task) if memory else []
    lessons_text = memory.format(lessons) if memory else ""
    used_ids = [lesson.id for lesson in lessons]

    prompt, editable = build_prompt(task, use_graph, lessons_text)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    attempts: list[Attempt] = []
    learned: list[str] = []
    shown: list[str] = []  # lessons put in front of the model during retries
    tried: list[dict[str, str]] = []  # the files of each attempt, to spot repeats
    earlier: list[str] = []  # one line per failed attempt
    for number in range(1, max_retries + 2):
        try:
            reply = model.complete(messages)
        except ModelRequestError as err:
            # e.g. the request was too long for the model's context window: the task fails, the run goes on.
            attempts.append(Attempt(number, False, "ModelError", str(err)[:300], [], used_ids))
            break
        except ModelInfraError as err:
            # Rate limit, size over the per-minute token limit, timeout...: not the model's fault.
            attempts.append(Attempt(number, False, "ApiError", str(err)[:300], [], used_ids))
            break
        files = parse_files(reply, task, editable)
        if files:
            result = verify(task.dir, files, timeout=timeout)
        else:
            result = VerifyResult(False, "No usable code block found. Reply with the full fixed file "
                                         "in a ```python block starting with '# file: <path>'.", "FormatError")
        attempts.append(Attempt(number, result.passed, result.error_type, result.output,
                                sorted(files), used_ids, "" if result.passed else reply[:500]))
        if result.passed:
            break
        lesson = memory.reflect(model, task, files, result) if memory and learn else None
        if lesson:
            learned.append(lesson.id)
        if number <= max_retries:
            feedback = ""
            if earlier:
                feedback += "Earlier attempts also failed:\n" + "\n".join(f"- {line}" for line in earlier) + "\n\n"
            feedback += f"Your latest attempt failed the tests:\n```\n{result.output}\n```\n"
            feedback += repeat_warning(files, task, tried)
            if lesson:
                feedback += f"Lesson from this failure: {lesson.text}\n"
                shown.append(lesson.id)
            earlier.append(f"attempt {number}: {headline(result.output)}")
            tried.append(files)
            # Keep the conversation short: the task, the latest attempt and its error. Older
            # attempts are only summarised above, so long retry chains never outgrow the context.
            messages = messages[:2] + [
                {"role": "assistant", "content": reply},
                {"role": "user", "content": feedback + "Find the cause and return the complete fixed file(s)."},
            ]

    passed = attempts[-1].passed
    result = TaskResult(task.id, passed, attempts, learned)
    if memory and learn and not result.errored:
        # Credit lessons only once the outcome is known (Harness²-style: keep what wins).
        memory.record_outcome(used_ids + shown, passed, task.id)
        memory.save()
    return result
