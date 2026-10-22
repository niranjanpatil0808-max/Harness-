"""Files people give to an agent, and files they take back.

Uploads are deliberately narrow: plain-text files only (notes, CSV, JSON, code, Markdown...), up to 1.5 MB each, never executed, never
overwriting anything. They are kept outside the agent's own folder, one folder per chat (`<workspace>/uploads/<agent>/<room>/`): the agent
reads them as `uploads/<name>` only while it works in that chat, so a file given in a private chat never shows up in another room, and code
the agent runs cannot reach them or plant links in their place. Binary files (PDF, images, Office) are refused with a clear message because the
agents read text. Downloads send the file as an attachment with a neutral type, so a browser never runs or renders it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .sandbox import PathError, safe_path

if TYPE_CHECKING:
    from .core import Workspace

MAX_FILE_BYTES = 1_500_000
MAX_FILES, MAX_TOTAL = 100, 20_000_000
NAME_ONLY = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,78}$")
TEXT_EXT = {"txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "yaml", "yml", "xml", "html", "htm", "css", "js", "ts", "tsx", "jsx", "py", "rb", "go", "rs",
            "java", "c", "h", "cpp", "hpp", "cs", "php", "sh", "sql", "toml", "ini", "cfg", "conf", "log", "tex", "rst", "env.example"}


class UploadError(Exception):
    """A file that cannot be accepted, with a reason the person can act on."""


def save(ws: "Workspace", agent: str, name: str, data_b64: str, room: str) -> str:
    from .core import WorkspaceError

    ws.get_agent(agent)
    name = (name or "").strip()
    if not NAME_RE.match(name) or ".." in name:
        raise UploadError("the file name must be 1-79 plain characters (letters, digits, dot, dash, underscore, space)")
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in TEXT_EXT:
        raise UploadError("only plain-text files can be given to an agent for now (notes, .md, .txt, .csv, .json, code...). PDFs, images and Office files are not supported yet")
    try:
        raw = base64.b64decode(data_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        raise UploadError("the file could not be read") from None
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise UploadError(f"the file is empty or larger than {MAX_FILE_BYTES // 1_000_000:.1f} MB")
    if b"\0" in raw:
        raise UploadError("that looks like a binary file, not text")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise UploadError("the file must be UTF-8 text") from None
    folder = room_folder(ws, agent, room)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink() or not folder.resolve().is_relative_to((ws.root / "uploads").resolve()):
        raise UploadError("the uploads folder is not usable")
    existing = [p for p in folder.iterdir() if p.is_file()]
    total = sum(p.stat().st_size for p in (ws.root / "uploads" / agent).rglob("*") if p.is_file() and not p.is_symlink())
    if len(existing) >= MAX_FILES or total + len(raw) > MAX_TOTAL:
        raise UploadError("this agent already holds as many uploaded files as allowed; delete some first")
    stem, dot, suffix = name.rpartition(".")
    candidate, n = name, 1
    while True:  # never overwrite, never follow a link, even when two uploads race
        try:
            fd = os.open(folder / candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            break
        except FileExistsError:
            n += 1
            if n > MAX_FILES + 1:
                raise UploadError("too many files with that name") from None
            candidate = f"{stem} ({n}).{suffix}" if dot else f"{name} ({n})"
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    ws.audit(agent, "file-uploaded", f"{room}/{candidate} {len(raw)} bytes")
    return f"uploads/{candidate}"


def room_folder(ws: "Workspace", agent: str, room: str) -> Path:
    if not room or not NAME_ONLY.match(agent or ""):
        raise UploadError("bad chat or agent name")
    return ws.root / "uploads" / agent / _room_key(room)


def _room_key(room: str) -> str:
    """A folder name for a chat: readable, and unique even for names with characters a folder should not have."""
    return re.sub(r"[^a-z0-9_-]", "_", room.lower())[:60] + "-" + hashlib.sha256(room.encode()).hexdigest()[:10]


def resolve(ws: "Workspace", agent: str, room: str, relative: str) -> Path:
    """The real path of `uploads/<name>` (or `uploads`) for this agent in this chat."""
    rest = relative.strip().lstrip("./")
    rest = rest[len("uploads"):].lstrip("/") if rest.startswith("uploads") else rest
    folder = room_folder(ws, agent, room)
    if not rest:
        return folder
    if not folder.is_dir():
        raise UploadError("nobody has given a file in this chat yet")
    try:
        return safe_path(folder, rest)
    except PathError as err:
        raise UploadError(str(err)) from None


def is_upload_path(relative: str) -> bool:
    rest = (relative or "").strip().lstrip("./")
    return rest == "uploads" or rest.startswith("uploads/")


def forget_room(ws: "Workspace", room: str) -> None:
    if room:
        for agent_folder in (ws.root / "uploads").glob("*"):
            shutil.rmtree(agent_folder / _room_key(room), ignore_errors=True)


def forget_agent(ws: "Workspace", agent: str) -> None:
    if NAME_ONLY.match(agent or ""):
        shutil.rmtree(ws.root / "uploads" / agent, ignore_errors=True)


def read_for_download(ws: "Workspace", agent: str, relative: str, room: str | None = None) -> tuple[str, bytes]:
    ws.get_agent(agent)
    try:
        path = resolve(ws, agent, room or "", relative) if room is not None else safe_path(ws.files_dir(agent), relative)
    except PathError as err:
        raise UploadError(str(err)) from None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 5_000_000:
        raise UploadError("no such file (or it is too large to download here)")
    return path.name, path.read_bytes()
