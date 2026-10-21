"""Run a task's unit tests in a separate process.

Model-written code is never imported into the harness process. Each check
copies the task to a fresh temp directory, writes the candidate files there
and runs `python -m unittest` with a timeout.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_ERROR_CHARS = 2000


@dataclass
class VerifyResult:
    passed: bool
    output: str
    error_type: str = ""  # e.g. "AssertionError", "Timeout", "SyntaxError"


def _error_type(output: str) -> str:
    """Pull the most specific exception name out of unittest output."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        head = line.split(":", 1)[0]
        if head.endswith(("Error", "Exception")) and head.replace(".", "").isidentifier():
            return head.rsplit(".", 1)[-1]
    return "TestFailure" if "FAIL" in output else ""


def trim(output: str, limit: int = MAX_ERROR_CHARS) -> str:
    """Keep the end of long outputs; the traceback tail is the useful part."""
    return output if len(output) <= limit else "...\n" + output[-limit:]


def verify(task_dir: Path, files: dict[str, str] | None = None, timeout: float = 10.0) -> VerifyResult:
    """Run the tests in `task_dir`, with `files` (relative path -> source) overlaid."""
    with tempfile.TemporaryDirectory(prefix="kintsugi-") as tmp:
        work = Path(tmp) / "task"
        shutil.copytree(task_dir, work, ignore=shutil.ignore_patterns("__pycache__", "task.json"))
        for rel, source in (files or {}).items():
            target = (work / rel).resolve()
            if work.resolve() not in target.parents:
                return VerifyResult(False, f"Refused to write outside the task: {rel}", "PathError")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
        env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"],
                cwd=work, env=env, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return VerifyResult(False, f"Tests timed out after {timeout}s (infinite loop?).", "Timeout")
    output = (proc.stdout + proc.stderr).strip()
    if proc.returncode == 0 and "Ran 0 tests" not in output:
        return VerifyResult(True, output)
    return VerifyResult(False, trim(output), _error_type(output) or "TestFailure")
