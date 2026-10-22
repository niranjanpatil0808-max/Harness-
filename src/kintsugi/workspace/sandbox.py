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


# Starts the user's script after lowering this process's own limits. Done in the child instead of with
# subprocess's preexec_fn, which Python documents as unsafe in a multi-threaded program (the server is one).
LAUNCHER = """import os, resource, runpy, sys
cpu, mem, fsize, script, cwd = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5]
resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
os.chdir(cwd)
sys.argv = [script]
runpy.run_path(script, run_name="__main__")
"""

# Runs inside new user, mount, pid, network and ipc namespaces (made by `unshare`), as an unprivileged "root" that
# maps back to the real user. It builds a private root that contains only a read-only Python and the agent's own
# folder, then chroots into it. The agent's code cannot see the workspace database, the keychain, the access token,
# other agents' folders, the server's environment, the home directory or the network.
NAMESPACE_SCRIPT = r"""set -e
PATH=/usr/sbin:/usr/bin:/sbin:/bin
CH=$1; SP=$2; PY=$3; LA=$4; CPU=$5; MEM=$6; FS=$7; SCR=$8; FOLDER=$9; shift 9; SD=$1; BASE=$2; shift 2
mount -t tmpfs tmpfs "$BASE"
R="$BASE/r"; mkdir "$R"
mkdir "$R/tmp"; mount -t tmpfs tmpfs "$R/tmp"
for d in "$@"; do
  mkdir -p "$R$d"; mount --rbind "$d" "$R$d"; mount -o remount,bind,ro "$R$d" 2>/dev/null || true
done
mkdir -p "$R/work" "$R/script" "$R/proc" "$R/dev" "$R/etc"
mount --bind "$FOLDER" "$R/work"
mount --bind "$SD" "$R/script"; mount -o remount,bind,ro "$R/script" 2>/dev/null || true
mount -t proc proc "$R/proc"
for n in null zero urandom random; do : > "$R/dev/$n"; mount --bind "/dev/$n" "$R/dev/$n"; done
PATH=$SANDBOX_PATH; export PATH
# Drop every capability (and forbid regaining any) before the agent's code starts: as the namespace's "root" it
# could otherwise chroot out of this private root. With an empty bounding set the exec'd Python has no capabilities.
exec "$CH" "$R" "$SP" --bounding-set=-all --inh-caps=-all --no-new-privs "$PY" -B -c "$LA" "$CPU" "$MEM" "$FS" "$SCR" /work
"""

STANDARD_ROOTS = ("/usr", "/lib", "/lib32", "/lib64", "/bin", "/sbin")
_backend: str | None = None
_backend_note = ""


def _inside(path: str, parent: str) -> bool:
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def _python_roots() -> list[str]:
    """Directories the sandboxed Python needs to exist (read-only)."""
    roots = [p for p in STANDARD_ROOTS if os.path.isdir(p)]
    if os.path.isdir("/etc/alternatives"):  # many `python` symlinks (venvs, Debian) point through here
        roots.append("/etc/alternatives")
    wanted = {sys.prefix, sys.base_prefix, sys.exec_prefix, str(Path(os.path.realpath(sys.executable)).parent.parent)}
    for path in sorted(wanted):
        path = os.path.realpath(path)
        if path != "/" and not any(_inside(path, r) for r in roots):
            roots = [r for r in roots if not _inside(r, path)] + [path]
    return roots


def _interpreter() -> str:
    """The Python to start inside the sandbox: resolved, unless this is a venv (which needs its own path)."""
    return sys.executable if sys.prefix != sys.base_prefix else os.path.realpath(sys.executable)


def _namespace_command(folder: Path, script_dir: Path, cpu: int, mem: int, fsize: int) -> list[str] | None:
    roots = _python_roots()
    paths = [str(folder.resolve()), str(script_dir.resolve()), *roots]
    base = next((d for d in ("/mnt", "/media", "/srv") if os.path.isdir(d) and not any(_inside(p, d) for p in paths)), None)
    if base is None or not all(shutil.which(tool) for tool in ("unshare", "mount", "chroot", "setpriv")):
        return None  # without setpriv the sandbox could not drop its privileges, so it must not be used
    return [shutil.which("unshare"), "--user", "--map-root-user", "--mount", "--pid", "--fork", "--kill-child", "--net", "--ipc", "--uts",
            "--", "sh", "-c", NAMESPACE_SCRIPT, "sh", shutil.which("chroot"), shutil.which("setpriv"), _interpreter(), LAUNCHER, str(cpu), str(mem), str(fsize),
            "/script/main.py", str(folder.resolve()), str(script_dir.resolve()), base, *roots]



def agent_uid(name: str) -> int:
    """A stable user id per agent for the drop-privileges backend (range 40000-59999)."""
    import zlib

    return 40000 + zlib.crc32(name.encode()) % 20000


def _run(command: list[str], cwd, env: dict, timeout: float, **kwargs) -> tuple[int | None, str]:
    proc = subprocess.Popen(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            start_new_session=True, **kwargs)  # own process group: a timeout kills the whole tree
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.communicate()
        return None, f"Timed out after {timeout:g}s (infinite loop?)."
    return proc.returncode, output


def backend() -> str:
    """Which isolation is available here: 'namespaces', 'drop-user' or 'process' (not isolated). Tested once."""
    global _backend, _backend_note
    if _backend is not None:
        return _backend
    forced = os.environ.get("KINTSUGI_SANDBOX_BACKEND", "").strip()
    if forced in ("namespaces", "drop-user", "process"):
        _backend, _backend_note = forced, "forced by KINTSUGI_SANDBOX_BACKEND"
        return _backend
    if os.name != "posix":
        _backend, _backend_note = "process", "this operating system has no supported isolation"
        return _backend
    _backend, _backend_note = "process", "no isolation is available (needs Linux user namespaces, or running as root in a container)"
    with tempfile.TemporaryDirectory(prefix="kw-probe-") as tmp:
        folder = Path(tmp) / "f"
        folder.mkdir()
        ok, output = _run_namespaces(folder, "print(40 + 2)", 10.0, {"PATH": "/usr/bin:/bin", "SANDBOX_PATH": "/usr/bin:/bin"}, 256)
        if ok and output.strip() == "42":
            _backend, _backend_note = "namespaces", "private root, no network, own process list"
            return _backend
    if os.geteuid() == 0:
        _backend, _backend_note = "drop-user", "runs as an unprivileged user id per agent (network is NOT blocked)"
    return _backend


def status() -> dict:
    name = backend()
    return {"backend": name, "isolated": name != "process", "network_blocked": name == "namespaces", "note": _backend_note}


def _run_namespaces(folder: Path, source: str, timeout: float, env: dict, memory_mb: int) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="kw-run-") as tmp:
        script_dir = Path(tmp)
        (script_dir / "main.py").write_text(source)
        command = _namespace_command(folder, script_dir, int(timeout) + 2, memory_mb * 1024 * 1024, MAX_FILE_BYTES * 5)
        if command is None:
            return False, "namespaces unavailable"
        code, output = _run(command, None, env, timeout)
    return _finish(code, output, timeout)


def _finish(code: int | None, output: str, timeout: float) -> tuple[bool, str]:
    if code is None:
        return False, output
    text = trim(output.strip(), MAX_OUTPUT_CHARS)
    signalled = -code if code < 0 else (code - 128 if code > 128 else 0)
    if signalled in (signal.SIGKILL, signal.SIGXCPU, signal.SIGSEGV, signal.SIGABRT):
        text = (text + "\n" if text else "") + f"(process was stopped by signal {signalled}: a CPU or memory limit?)"
    return code == 0, text or "(no output)"


def run_python(folder: Path, source: str, timeout: float = 10.0, extra_env: dict[str, str] | None = None,
               memory_mb: int = 1024, agent: str | None = None) -> tuple[bool, str]:
    """Run `source` with the agent's folder as the working directory. Returns (ok, output).

    Uses the strongest isolation available (see backend()). In 'process' mode the code runs as you, with your
    files and network: only approve code you would run yourself."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    timeout = min(max(float(timeout), 1.0), 60.0) if timeout == timeout else 10.0  # also handles NaN
    mode = backend()
    if mode == "process" and os.environ.get("KINTSUGI_SANDBOX", "auto") == "require":
        return False, "run_python is disabled: KINTSUGI_SANDBOX=require and this machine cannot isolate code."
    inside = mode == "namespaces"
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "SANDBOX_PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work" if inside else str(folder), "LANG": "C.UTF-8",
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", **(extra_env or {})}
    if inside:
        ok, output = _run_namespaces(folder, source, timeout, env, memory_mb)
        if output != "namespaces unavailable":
            return ok, output
    with tempfile.TemporaryDirectory(prefix="kw-run-") as tmp:
        script = Path(tmp) / "main.py"
        script.write_text(source)
        os.chmod(tmp, 0o755)
        os.chmod(script, 0o644)
        kwargs: dict = {}
        if mode == "drop-user" and os.geteuid() == 0:
            uid = agent_uid(agent or "anonymous")
            _chown_tree(folder, uid)
            kwargs = {"user": uid, "group": uid, "extra_groups": []}
        command = [sys.executable, "-B", "-c", LAUNCHER, str(int(timeout) + 2), str(memory_mb * 1024 * 1024),
                   str(MAX_FILE_BYTES * 5), str(script), str(folder)] if os.name == "posix" else [sys.executable, "-B", str(script)]
        if os.name != "posix":
            proc = subprocess.run(command, cwd=folder, env=env, text=True, capture_output=True, timeout=timeout)
            return proc.returncode == 0, trim((proc.stdout + proc.stderr).strip(), MAX_OUTPUT_CHARS) or "(no output)"
        code, output = _run(command, folder, env, timeout, **kwargs)
    return _finish(code, output, timeout)


def _chown_tree(folder: Path, uid: int) -> None:
    for path in [folder, *folder.rglob("*")]:
        try:
            os.chown(path, uid, uid, follow_symlinks=False)
        except OSError:
            pass


def wipe(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)
