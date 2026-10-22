"""An agent's durable folder and a process-level sandbox to run its code.

This is NOT a security sandbox. Code runs as a subprocess with the same user and network access as
the server; the limits below (timeout, CPU, memory, file size, folder only, scrubbed environment) stop
accidents and runaway loops, not a determined attacker. Use a container or VM for untrusted code.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from kintsugi.verifier import trim

MAX_FILE_BYTES = 200_000  # one file written by a tool
MAX_FOLDER_BYTES = 5_000_000  # everything in an agent's folder
MAX_OUTPUT_CHARS = 4000


class PathError(ValueError):
    """A path that leaves the agent's folder or is otherwise not allowed."""


def safe_path(base: Path, relative: str) -> Path:
    """Resolve `relative` inside `base`; refuse absolute paths, '..' and symlinks that escape."""
    if not isinstance(relative, str) or not relative.strip() or "\0" in relative:
        raise PathError("empty or invalid path")
    if Path(relative).is_absolute() or relative.startswith(("~", "\\")):
        raise PathError("absolute paths are not allowed")
    base = base.resolve()
    target = (base / relative).resolve()
    if target != base and base not in target.parents:
        raise PathError("path leaves the agent's folder")
    return target


def folder_size(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())


def _limits(cpu_seconds: int, memory_mb: int):
    """Resource limits applied in the child process (POSIX only)."""
    def apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024, memory_mb * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_BYTES * 5, MAX_FILE_BYTES * 5))
        os.setsid()
    return apply


def run_python(folder: Path, source: str, timeout: float = 10.0, extra_env: dict[str, str] | None = None,
               memory_mb: int = 1024) -> tuple[bool, str]:
    """Run `source` with the agent's folder as the working directory. Returns (ok, output)."""
    folder.mkdir(parents=True, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(folder), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **(extra_env or {})}
    with tempfile.TemporaryDirectory(prefix="kw-run-") as tmp:
        script = Path(tmp) / "main.py"
        script.write_text(source)
        kwargs = {"preexec_fn": _limits(int(timeout) + 2, memory_mb)} if os.name == "posix" else {}
        proc = subprocess.Popen([sys.executable, "-B", str(script)], cwd=folder, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            proc.communicate()
            return False, f"Timed out after {timeout:g}s (infinite loop?)."
    text = trim(output.strip(), MAX_OUTPUT_CHARS)
    if proc.returncode is not None and proc.returncode < 0:
        text = (text + "\n" if text else "") + f"(process was stopped by signal {-proc.returncode}: a CPU or memory limit?)"
    return proc.returncode == 0, text or "(no output)"


def wipe(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
