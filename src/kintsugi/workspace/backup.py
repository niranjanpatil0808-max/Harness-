"""Encrypted backups to a private GitHub repository, and restoring them onto an empty server.

Why: free hosting erases the server's disk on every restart. This keeps one encrypted copy of your whole workspace (chats,
agents, files, lessons, settings, secrets) in a repository only you can see, and brings it back when the server starts empty.

How it is kept safe:
  * Everything is encrypted on the server BEFORE it leaves, with a key made from your passphrase (PBKDF2-HMAC-SHA256, 600,000
    rounds, random salt, then Fernet = AES-128-CBC + HMAC). GitHub only ever sees an opaque blob. Lose the passphrase and the
    backup cannot be read by anyone, including us.
  * The repository must be PRIVATE: the backup refuses to run against a public one.
  * The GitHub token, repository and passphrase come from environment variables (your hosting dashboard's secrets), never from
    the app's own database: after a wipe that database is gone, and the settings must survive it. The token should be a
    fine-grained token limited to that one repository with "Contents: read and write".
  * The only host called is api.github.com.
  * A restore only happens onto an EMPTY workspace (or with an explicit force on the command line).

Needs the optional `cryptography` package (pip install "kintsugi[push]").
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

try:  # optional dependency
    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:  # pragma: no cover - exercised through available()
    Fernet = InvalidToken = hashes = PBKDF2HMAC = None

MAGIC = b"KTB1"
KDF_ROUNDS = 600_000
MAX_BACKUP_BYTES = 25 * 1024 * 1024  # GitHub's contents API is meant for modest files; bigger means "time to clean up"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
DEFAULT_PATH = "kintsugi-backup.enc"
GITHUB = "https://api.github.com"
SKIP = {"token"}  # the access token is managed through the environment, not carried in backups
USER_AGENT = "kintsugi-workspace-backup"


class BackupError(Exception):
    """A backup or restore that failed in a way worth showing to the owner (never contains the token or passphrase)."""


def available() -> bool:
    return Fernet is not None


def config() -> dict | None:
    """Backup settings from the environment, or None when backups are not set up."""
    repo = os.environ.get("KINTSUGI_BACKUP_REPO", "").strip()
    token = os.environ.get("KINTSUGI_BACKUP_TOKEN", "").strip()
    passphrase = os.environ.get("KINTSUGI_BACKUP_PASSPHRASE", "")
    if not (repo and token and passphrase):
        return None
    if not REPO_RE.match(repo):
        raise BackupError("KINTSUGI_BACKUP_REPO must look like owner/repository")
    if len(passphrase) < 12:
        raise BackupError("KINTSUGI_BACKUP_PASSPHRASE must be at least 12 characters (it is the only thing protecting your backup)")
    path = os.environ.get("KINTSUGI_BACKUP_PATH", DEFAULT_PATH).strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", path) or ".." in path:
        raise BackupError("KINTSUGI_BACKUP_PATH is not a safe file path")
    try:
        minutes = max(5, int(os.environ.get("KINTSUGI_BACKUP_EVERY_MINUTES", "60")))
    except ValueError:
        minutes = 60
    return {"repo": repo, "token": token, "passphrase": passphrase, "path": path, "every_minutes": minutes}


# --- the encrypted container ---------------------------------------------------------

def _key(passphrase: str, salt: bytes) -> bytes:
    return base64.urlsafe_b64encode(PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=KDF_ROUNDS).derive(passphrase.encode()))


def encrypt(data: bytes, passphrase: str) -> bytes:
    if not available():
        raise BackupError("backups need the optional 'cryptography' package (pip install 'kintsugi[push]')")
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_key(passphrase, salt)).encrypt(data)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    if not available():
        raise BackupError("backups need the optional 'cryptography' package (pip install 'kintsugi[push]')")
    if not blob.startswith(MAGIC) or len(blob) < 21:
        raise BackupError("that file is not a Kintsugi backup")
    try:
        return Fernet(_key(passphrase, blob[4:20])).decrypt(blob[20:])
    except InvalidToken:
        raise BackupError("could not decrypt the backup: wrong passphrase, or the file was changed") from None


# --- packing the workspace -------------------------------------------------------------

META_NAME = "backup.meta.json"
STALE_SECONDS = 6 * 3600  # a backup this much older than the newest one in GitHub looks like a replayed old file


def next_counter(ws: "Workspace") -> int:
    try:
        return int(ws.get_setting("backup_counter", "0") or 0) + 1
    except ValueError:
        return 1


def read_meta(data: bytes) -> dict | None:
    """The backup number and time stored inside a (decrypted) backup, or None for one made before this existed."""
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = next((m for m in tar.getmembers() if m.name == META_NAME and m.isreg() and m.size < 4096), None)
            if member is None:
                return None
            meta = json.loads(tar.extractfile(member).read())
        return {"counter": int(meta["counter"]), "created": float(meta["created"])} if isinstance(meta, dict) else None
    except (tarfile.TarError, OSError, ValueError, KeyError, TypeError, EOFError):
        return None


def snapshot(ws: "Workspace", counter: int | None = None) -> bytes:
    """One consistent tar.gz of the workspace: a safe copy of the database plus every folder (not the access token)."""
    counter = next_counter(ws) if counter is None else counter
    with tempfile.TemporaryDirectory(prefix="kw-backup-") as tmp:
        copy = Path(tmp) / "workspace.db"
        target = sqlite3.connect(str(copy))
        with ws.db.lock:
            ws.db.conn.backup(target)  # a consistent copy even while agents are writing
        target.close()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            tar.add(copy, arcname="workspace.db")
            meta = json.dumps({"counter": counter, "created": ws.clock()}).encode()
            info = tarfile.TarInfo(META_NAME)
            info.size, info.mtime, info.mode = len(meta), int(ws.clock()), 0o600
            tar.addfile(info, io.BytesIO(meta))
            for item in sorted(ws.root.iterdir()):
                if item.name in SKIP or item.name.startswith("workspace.db") or item.is_symlink():
                    continue
                tar.add(item, arcname=item.name, filter=lambda info: info if info.isreg() or info.isdir() else None)  # never links, pipes or devices: restore refuses them
        data = buffer.getvalue()
    if len(data) > MAX_BACKUP_BYTES:
        raise BackupError(f"the workspace is {len(data) // 1_000_000} MB, over the {MAX_BACKUP_BYTES // 1_000_000} MB backup limit: delete old files or chats")
    return data


def _safe_members(tar: tarfile.TarFile):
    for member in tar.getmembers():
        name = member.name
        if member.issym() or member.islnk() or member.isdev() or name.startswith(("/", "..")) or ".." in Path(name).parts:
            raise BackupError("the backup contains an unsafe path; it was not restored")
        yield member


def unpack(data: bytes, root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members = [m for m in _safe_members(tar) if m.name != META_NAME]
        tar.extractall(root, members=members, filter="data") if hasattr(tarfile, "data_filter") else tar.extractall(root, members=members)  # noqa: S202 - every member was checked above (no links, devices or escapes)
    lock_down(root)


def lock_down(root: Path) -> None:
    """Restored files get the same private permissions a fresh workspace has: nothing readable by other users.
    (The workspace re-opens the few folders that must be reachable, such as agents' published apps, when it starts.)"""
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def is_empty(root: Path) -> bool:
    """True when there is nothing worth protecting: no database, or a database with no agents and no messages."""
    db = root / "workspace.db"
    if not db.exists():
        return True
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return conn.execute("SELECT (SELECT COUNT(*) FROM agents) + (SELECT COUNT(*) FROM messages)").fetchone()[0] == 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False  # unreadable: never overwrite something we do not understand


# --- GitHub ----------------------------------------------------------------------------------

def _api(cfg: dict, method: str, path: str, body: dict | None = None, raw: bool = False, timeout: float = 60.0):
    base = os.environ.get("KINTSUGI_GITHUB_API", GITHUB).rstrip("/")  # tests point this at a fake; only the operator controls it
    headers = {"Authorization": f"Bearer {cfg['token']}", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": USER_AGENT,
               "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json"}
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_BACKUP_BYTES * 2 + 1)
            if len(payload) > MAX_BACKUP_BYTES * 2:
                raise BackupError("the backup file is larger than the allowed size")
            return payload if raw else (json.loads(payload) if payload else {})
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        if err.code in (401, 403):
            raise BackupError("GitHub refused the token (check it is valid and has 'Contents: read and write' on the backup repository)") from None
        raise BackupError(f"GitHub answered with an error ({err.code})") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise BackupError("could not reach GitHub") from None


def check_repo(cfg: dict) -> None:
    info = _api(cfg, "GET", f"/repos/{cfg['repo']}")
    if info is None:
        raise BackupError("the backup repository was not found (or the token cannot see it)")
    if not info.get("private"):
        raise BackupError("the backup repository is PUBLIC. Make it private first: backups are encrypted, but they should not be public at all")


def upload(cfg: dict, blob: bytes) -> None:
    check_repo(cfg)
    current = _api(cfg, "GET", f"/repos/{cfg['repo']}/contents/{cfg['path']}")
    body = {"message": "Kintsugi encrypted backup", "content": base64.b64encode(blob).decode()}
    if current and current.get("sha"):
        body["sha"] = current["sha"]
    _api(cfg, "PUT", f"/repos/{cfg['repo']}/contents/{cfg['path']}", body, timeout=120.0)


def download(cfg: dict) -> bytes | None:
    check_repo(cfg)
    return _api(cfg, "GET", f"/repos/{cfg['repo']}/contents/{cfg['path']}", raw=True, timeout=120.0)


def remote_modified(cfg: dict) -> float | None:
    """When GitHub last committed the backup file (best effort: None if it cannot be told)."""
    from datetime import datetime

    try:
        commits = _api(cfg, "GET", f"/repos/{cfg['repo']}/commits?path={cfg['path']}&per_page=1")
        stamp = commits[0]["commit"]["committer"]["date"]
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (BackupError, KeyError, IndexError, TypeError, ValueError):
        return None


def restore_if_empty(root: Path, say=print) -> bool:
    """At startup: if this workspace folder is empty and backups are configured, bring the backup back. Returns True if restored."""
    cfg = config()
    if cfg is None or not available() or not is_empty(Path(root)):
        return False
    try:
        blob = download(cfg)
        if blob is None:
            say("Backups are on, but there is no backup in the repository yet. Starting fresh.")
            return False
        data = decrypt(blob, cfg["passphrase"])
        meta = read_meta(data)
        newest = remote_modified(cfg)
        if meta and newest and newest - meta["created"] > STALE_SECONDS and os.environ.get("KINTSUGI_BACKUP_ACCEPT_OLD") != "1":
            raise BackupError(f"the backup file in GitHub was made {time.strftime('%Y-%m-%d %H:%M', time.gmtime(meta['created']))} UTC but was committed much later "
                              f"({time.strftime('%Y-%m-%d %H:%M', time.gmtime(newest))} UTC): it may be an old copy put back. Nothing was restored. "
                              "If you are sure, set KINTSUGI_BACKUP_ACCEPT_OLD=1 and start again")
        unpack(data, Path(root))
        if meta:
            conn = sqlite3.connect(str(Path(root) / "workspace.db"))
            try:
                conn.execute("INSERT INTO settings (key, value) VALUES ('backup_counter', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(meta["counter"]),))
                conn.commit()
            finally:
                conn.close()
    except (BackupError, OSError, tarfile.TarError, EOFError, ValueError) as err:  # a damaged backup must never stop the server from starting
        say(f"Could not restore the backup: {err}. Starting fresh; nothing was overwritten.")
        return False
    say("Restored your workspace from the encrypted backup.")
    return True


# --- running backups ---------------------------------------------------------------------------

class Backups:
    def __init__(self, ws: "Workspace") -> None:
        self.ws = ws
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_check = 0.0
        self._last_print = None

    def status(self) -> dict:
        raw = self.ws.get_setting("backup_last", "")
        try:
            last = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            last = None
        try:
            cfg = config()
            problem = ""
        except BackupError as err:
            cfg, problem = None, str(err)
        return {"available": available(), "configured": cfg is not None, "problem": problem, "repo": cfg["repo"] if cfg else "",
                "every_minutes": cfg["every_minutes"] if cfg else None, "last": last, "running": self.running()}

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def fingerprint(self) -> str:
        """Cheap 'has anything changed?' value: newest rows plus the size and age of every file."""
        db = self.ws.db
        settings = db.query("SELECT key, value FROM settings WHERE key NOT IN ('backup_last', 'backup_counter') ORDER BY key")
        parts = [db.one("SELECT COALESCE(MAX(id), 0) AS n FROM messages")["n"], db.one("SELECT COUNT(*) AS n FROM notes")["n"],
                 db.one("SELECT COALESCE(MAX(id), 0) AS n FROM audit WHERE event NOT LIKE 'backup%'")["n"],
                 [(r["key"], r["value"]) for r in settings], [tuple(r.values()) for r in db.query("SELECT * FROM agents ORDER BY name")]]
        for path in sorted((self.ws.root / "agents").rglob("*")):
            if path.is_file():
                stat = path.stat()
                parts.append((path.name, stat.st_size, int(stat.st_mtime)))
        return repr(parts)

    def _check_remote(self, cfg: dict, counter: int) -> None:
        """Do not overwrite a backup that is newer than anything this workspace has written, or one it cannot read: that means another
        copy of the workspace is writing to the same place, or this one is a fresh start about to erase a real backup."""
        if os.environ.get("KINTSUGI_BACKUP_OVERWRITE") == "1":
            return
        remote = download(cfg)
        if remote is None:
            return
        try:
            meta = read_meta(decrypt(remote, cfg["passphrase"]))
        except BackupError:
            raise BackupError("the backup already in GitHub cannot be read with this passphrase, so it was not overwritten. Use the same passphrase, "
                              "or set KINTSUGI_BACKUP_OVERWRITE=1 to replace it on purpose") from None
        if meta and meta["counter"] >= counter:
            raise BackupError(f"the backup in GitHub (#{meta['counter']}) is newer than this workspace's last one (#{counter - 1}); another copy of the workspace may "
                              "be writing to it, or this workspace is a fresh start. It was not overwritten. Restore from it, or set KINTSUGI_BACKUP_OVERWRITE=1 to replace it on purpose")

    def run(self, force: bool = False) -> dict:
        """Back up now (blocking). Records the outcome; never raises."""
        result = {"ts": self.ws.clock(), "ok": False, "bytes": 0, "error": ""}
        try:
            cfg = config()
            if cfg is None:
                raise BackupError("backups are not set up (see docs/HOSTING.md)")
            if not force and self.fingerprint() == self._last_print:
                return {**result, "ok": True, "error": "nothing changed since the last backup"}
            before = self.fingerprint()  # taken first: anything that changes during the upload triggers the next backup
            counter = next_counter(self.ws)
            self._check_remote(cfg, counter)
            blob = encrypt(snapshot(self.ws, counter), cfg["passphrase"])
            upload(cfg, blob)
            self.ws.set_setting("backup_counter", str(counter))
            self._last_print = before
            result.update(ok=True, bytes=len(blob))
            self.ws.audit(None, "backup-ok", f"{len(blob)} bytes")
        except BackupError as err:
            result["error"] = str(err)
            self.ws.audit(None, "backup-failed", str(err)[:200])
        except Exception as err:  # never let a backup problem take the workspace down
            result["error"] = f"unexpected problem: {type(err).__name__}"
            self.ws.audit(None, "backup-failed", f"{type(err).__name__}: {str(err)[:150]}")
        if result["ok"] and result["error"].startswith("nothing changed"):
            return result
        self.ws.set_setting("backup_last", json.dumps(result))
        return result

    def start(self, force: bool = True) -> bool:
        with self._lock:
            if self.running():
                return False
            self._thread = threading.Thread(target=self.run, kwargs={"force": force}, name="kintsugi-backup", daemon=True)
            self._thread.start()
            return True

    def maybe_run(self, now: float | None = None) -> bool:
        """Called by the scheduler: back up when it is time and something changed. Cheap between runs."""
        now = self.ws.clock() if now is None else now
        if now - self._last_check < 60:
            return False
        self._last_check = now
        try:
            cfg = config()
        except BackupError:
            return False
        if cfg is None or not available() or self.running():
            return False
        last = self.status()["last"]
        if last and now - last.get("ts", 0) < cfg["every_minutes"] * 60:
            return False
        return self.start(force=False)

    def stop(self) -> None:
        if self._thread is not None:
            self._thread.join(timeout=30)
