"""Mistake memory.

After a failed attempt the model writes a short, general lesson (Reflexion-style
self-reflection). Lessons live in a plain JSON file, are deduplicated, and the
most relevant ones are shown on later tasks as a short guide.

Each lesson keeps its evidence: which task produced it and how it did when it
was used. A lesson starts as a "candidate" and is "promoted" only after a task
that used it passed; lessons that keep being used without helping are pruned.
The model never changes, only this file does.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .loop import Task
    from .model import Model
    from .verifier import VerifyResult

REFLECT_PROMPT = """Your fix for a Python bug failed its tests.

Task: {description}

Test output:
```
{output}
```

Write ONE short, general lesson (max 2 sentences) that would help avoid this
kind of mistake on OTHER tasks. Do not mention this task's function names.
Start with "When". Reply with the lesson only."""

STOPWORDS = set("""a an the and or of to in on for with is are be by it its this that as at from
should return returns value values when if not do does use using must given into your you
than then else any all each one two only also can will which their them they was were has have
def self none true false""".split())

DEDUP_THRESHOLD = 0.6
PRUNE_AFTER_USES = 3
TOP_K = 3
MAX_LESSON_CHARS = 300


def tokens(text: str) -> set[str]:
    """Lowercase word tokens; snake_case and camelCase are split into parts."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return {w for w in words if w not in STOPWORDS}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass
class Lesson:
    id: str
    text: str
    error_type: str
    keywords: list[str]
    status: str = "candidate"  # candidate -> promoted, or pruned
    seen: int = 1  # how many failures produced this (or a near-duplicate) lesson
    uses: int = 0  # how many tasks it was shown to
    wins: int = 0  # how many of those tasks passed
    evidence: list[dict] = field(default_factory=list)


@dataclass
class MemoryStore:
    path: Path | None = None
    lessons: list[Lesson] = field(default_factory=list)
    top_k: int = TOP_K

    @classmethod
    def load(cls, path: Path) -> "MemoryStore":
        path = Path(path)
        lessons = []
        if path.exists():
            lessons = [Lesson(**item) for item in json.loads(path.read_text())["lessons"]]
        return cls(path, lessons)

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "lessons": [asdict(lesson) for lesson in self.lessons]}
        self.path.write_text(json.dumps(data, indent=2) + "\n")

    @property
    def active(self) -> list[Lesson]:
        return [lesson for lesson in self.lessons if lesson.status != "pruned"]

    # --- writing lessons -------------------------------------------------

    def add(self, text: str, error_type: str, context_words: set[str], task_id: str) -> Lesson:
        """Store a lesson, or merge it into a near-duplicate that already exists."""
        text = " ".join(text.split())[:MAX_LESSON_CHARS]
        words = tokens(text)
        for lesson in self.active:
            if jaccard(words, tokens(lesson.text)) >= DEDUP_THRESHOLD:
                lesson.seen += 1
                lesson.keywords = sorted(set(lesson.keywords) | context_words)
                lesson.evidence.append({"task": task_id, "event": "seen-again", "error": error_type})
                return lesson
        lesson = Lesson(
            id=f"L{len(self.lessons) + 1:03d}",
            text=text,
            error_type=error_type,
            keywords=sorted(words | context_words),
            evidence=[{"task": task_id, "event": "created", "error": error_type}],
        )
        self.lessons.append(lesson)
        return lesson

    def reflect(self, model: "Model", task: "Task", files: dict[str, str], result: "VerifyResult") -> Lesson | None:
        """Ask the model what went wrong and store the answer as a lesson."""
        if result.error_type == "FormatError":
            return None  # a formatting slip teaches nothing about the bug
        reply = model.complete([{"role": "user", "content": REFLECT_PROMPT.format(
            description=task.description, output=result.output[-1200:])}])
        text = reply.strip().strip('"').strip()
        if len(text) < 15:
            return None
        return self.add(text, result.error_type, task_words(task), task.id)

    # --- reading lessons -------------------------------------------------

    def retrieve(self, task: "Task") -> list[Lesson]:
        """Top lessons by keyword overlap with the task, nudged by their track record."""
        query = task_words(task)
        scored = []
        for lesson in self.active:
            if all(e["task"] == task.id for e in lesson.evidence):
                continue  # never feed a task its own lesson
            overlap = len(query & set(lesson.keywords))
            if overlap == 0:
                continue
            relevance = overlap / math.sqrt(len(lesson.keywords))
            track = (lesson.wins + 1) / (lesson.uses + 2)  # Laplace-smoothed win rate
            bonus = 0.25 if lesson.status == "promoted" else 0.0
            scored.append((relevance * (0.5 + track) + bonus, lesson))
        scored.sort(key=lambda pair: -pair[0])
        return [lesson for _, lesson in scored[: self.top_k]]

    @staticmethod
    def format(lessons: list[Lesson]) -> str:
        if not lessons:
            return ""
        lines = "\n".join(f"- {lesson.text}" for lesson in lessons)
        return f"Lessons from earlier mistakes (use them if they apply):\n{lines}"

    # --- keeping what works ----------------------------------------------

    def record_outcome(self, lesson_ids: list[str], passed: bool, task_id: str) -> None:
        by_id = {lesson.id: lesson for lesson in self.lessons}
        for lesson_id in dict.fromkeys(lesson_ids):
            lesson = by_id.get(lesson_id)
            if lesson is None:
                continue
            lesson.uses += 1
            lesson.wins += int(passed)
            lesson.evidence.append({"task": task_id, "event": "used", "passed": passed})
            if passed and lesson.status == "candidate":
                lesson.status = "promoted"
            elif lesson.uses >= PRUNE_AFTER_USES and lesson.wins == 0:
                lesson.status = "pruned"


def task_words(task: "Task") -> set[str]:
    """Words describing a task: its description plus identifiers in its code."""
    words = tokens(task.description)
    for code in task.sources.values():
        words |= tokens(" ".join(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", code)))
    return words
