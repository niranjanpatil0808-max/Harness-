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

from .model import Model
from .verifier import VerifyResult, verify

if TYPE_CHECKING:
    from .graph import ContextGraph
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


def parse_files(reply: str, task: Task) -> dict[str, str]:
    """Extract {path: code} from the model reply, ignoring edits to tests or unknown files."""
    files: dict[str, str] = {}
    for fence_name, body in BLOCK_RE.findall(reply):
        name = fence_name
        tag = FILE_TAG_RE.match(body)
        if tag:
            name = tag.group(1)
            body = body[tag.end():]
        if not name and len(task.sources) == 1:
            name = next(iter(task.sources))  # untagged block, only one file it can be
        name = name.removeprefix("./") if name else name
        if name in task.sources:
            files[name] = body.rstrip() + "\n"
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


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    attempts: list[Attempt]
    lessons_learned: list[str] = field(default_factory=list)

    @property
    def num_attempts(self) -> int:
        return len(self.attempts)


def build_prompt(task: Task, graph: "ContextGraph | None", lessons_text: str) -> str:
    if graph is not None:
        code = graph.context_for(task)
    else:
        code = format_files(task.sources)
    parts = [f"Task: {task.description}"]
    if lessons_text:
        parts.append(lessons_text)
    parts.append(f"Source files:\n{code}")
    parts.append(f"Tests (do not edit):\n{format_files(task.tests)}")
    parts.append("Return the fixed source file(s).")
    return "\n\n".join(parts)


def solve(
    task: Task,
    model: Model,
    max_retries: int = 3,
    memory: "MemoryStore | None" = None,
    graph: "ContextGraph | None" = None,
    learn: bool = True,
    timeout: float = 10.0,
) -> TaskResult:
    """Run one task through the loop. `max_retries=0` is the plain single-shot baseline."""
    lessons = memory.retrieve(task) if memory else []
    lessons_text = memory.format(lessons) if memory else ""
    used_ids = [lesson.id for lesson in lessons]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_prompt(task, graph, lessons_text)},
    ]
    attempts: list[Attempt] = []
    learned: list[str] = []
    for number in range(1, max_retries + 2):
        reply = model.complete(messages)
        files = parse_files(reply, task)
        if files:
            result = verify(task.dir, files, timeout=timeout)
        else:
            result = VerifyResult(False, "No usable code block found. Reply with the full fixed file "
                                         "in a ```python block starting with '# file: <path>'.", "FormatError")
        attempts.append(Attempt(number, result.passed, result.error_type, result.output,
                                sorted(files), used_ids))
        if result.passed:
            break
        if memory and learn:
            lesson = memory.reflect(model, task, files, result)
            if lesson:
                learned.append(lesson.id)
        if number <= max_retries:
            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content":
                             f"The tests failed:\n```\n{result.output}\n```\n"
                             "Find the cause and return the complete fixed file(s)."})

    passed = attempts[-1].passed
    if memory and learn:
        # Credit lessons only when the outcome is known (Harness²-style: keep what wins).
        memory.record_outcome(used_ids, passed, retried=len(attempts) > 1)
        memory.save()
    return TaskResult(task.id, passed, attempts, learned)
