"""Command line entry point.

  kintsugi fix <task_dir> [--no-memory] [--no-graph] [--retries N] [--mock]
  kintsugi graph <task_dir>
  kintsugi lessons [--memory PATH]
  kintsugi models
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .graph import ContextGraph
from .loop import load_task, solve
from .memory import MemoryStore
from .model import MockModel, OpenAIAdapter

DEFAULT_MEMORY = Path("memory/lessons.json")


def cmd_fix(args: argparse.Namespace) -> int:
    task = load_task(args.task_dir)
    model = MockModel() if args.mock else OpenAIAdapter()
    memory = None if args.no_memory else MemoryStore.load(args.memory)
    result = solve(task, model, max_retries=args.retries, memory=memory, use_graph=not args.no_graph)
    for attempt in result.attempts:
        status = "passed" if attempt.passed else f"failed ({attempt.error_type})"
        print(f"attempt {attempt.number}: {status}")
        if not attempt.passed and args.verbose:
            print(attempt.output)
    if memory and result.lessons_learned:
        by_id = {lesson.id: lesson for lesson in memory.lessons}
        for lesson_id in dict.fromkeys(result.lessons_learned):
            print(f"lesson {lesson_id}: {by_id[lesson_id].text}")
    print(f"{task.id}: {'PASS' if result.passed else 'FAIL'} in {result.num_attempts} attempt(s), "
          f"{model.usage.calls} model call(s)")
    print("(the task files on disk are not modified; fixes are only tested in a temp copy)")
    return 0 if result.passed else 1


def cmd_graph(args: argparse.Namespace) -> int:
    task = load_task(args.task_dir)
    graph = ContextGraph.build(task.sources)
    print(graph.describe())
    text, editable = graph.context_for(task)
    print(f"\nFiles shown in full for this task: {', '.join(editable)}\n")
    print(text)
    return 0


def cmd_lessons(args: argparse.Namespace) -> int:
    store = MemoryStore.load(args.memory)
    if not store.lessons:
        print(f"No lessons in {args.memory}")
    for lesson in store.lessons:
        print(f"{lesson.id} [{lesson.status}] seen={lesson.seen} used={lesson.uses} wins={lesson.wins}\n"
              f"    {lesson.text}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    model = OpenAIAdapter()
    print(f"Models available at {model.base_url}:")
    for name in model.list_models():
        print(f"  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kintsugi", description="Fix bugs with a small model that learns from its mistakes.")
    sub = parser.add_subparsers(dest="command", required=True)

    fix = sub.add_parser("fix", help="fix one task folder (source files + test_*.py + task.json)")
    fix.add_argument("task_dir", type=Path)
    fix.add_argument("--retries", type=int, default=3)
    fix.add_argument("--no-memory", action="store_true")
    fix.add_argument("--no-graph", action="store_true")
    fix.add_argument("--memory", type=Path, default=DEFAULT_MEMORY)
    fix.add_argument("--mock", action="store_true", help="use the offline mock model (it never fixes anything)")
    fix.add_argument("-v", "--verbose", action="store_true", help="print test output of failed attempts")
    fix.set_defaults(func=cmd_fix)

    graph = sub.add_parser("graph", help="show the context graph and what the model would see")
    graph.add_argument("task_dir", type=Path)
    graph.set_defaults(func=cmd_graph)

    lessons = sub.add_parser("lessons", help="list stored lessons")
    lessons.add_argument("--memory", type=Path, default=DEFAULT_MEMORY)
    lessons.set_defaults(func=cmd_lessons)

    models = sub.add_parser("models", help="list the model names your API key can use")
    models.set_defaults(func=cmd_models)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
