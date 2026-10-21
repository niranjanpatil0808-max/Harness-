"""Sanity-check the benchmark: every buggy task must fail, every reference fix must pass."""

import sys
from pathlib import Path

from kintsugi.verifier import verify

ROOT = Path(__file__).parent


def main() -> int:
    problems = 0
    task_dirs = sorted(p for p in (ROOT / "tasks").iterdir() if p.is_dir())
    for task_dir in task_dirs:
        solution_dir = ROOT / "solutions" / task_dir.name
        fixed = {p.name: p.read_text() for p in solution_dir.glob("*.py")}
        buggy_ok = not verify(task_dir).passed
        fixed_result = verify(task_dir, fixed)
        status = "ok" if buggy_ok and fixed_result.passed else "PROBLEM"
        if status != "ok":
            problems += 1
            detail = "buggy version passes" if not buggy_ok else fixed_result.output[-400:]
            print(f"{task_dir.name}: {status}\n{detail}\n")
        else:
            print(f"{task_dir.name}: ok")
    print(f"\n{len(task_dirs) - problems}/{len(task_dirs)} tasks valid")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
