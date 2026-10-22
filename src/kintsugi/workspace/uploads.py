"""Files people give to an agent, and files they take back.

Uploads are deliberately narrow: plain-text files only (notes, CSV, JSON, code, Markdown...), up to 1.5 MB each, saved under the agent's own
`uploads/` folder, never executed, never overwriting anything. Binary files (PDF, images, Office) are refused with a clear message because the
agents read text. Downloads send the file as an attachment with a neutral type, so a browser never runs or renders it.
"""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path
from typing import TYPE_CHECKING

from .sandbox import PathError, folder_size, safe_path

if TYPE_CHECKING:
    from .core import Workspace

MAX_FILE_BYTES = 1_500_000
MAX_FILES, MAX_TOTAL = 100, 20_000_000
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,78}$")
TEXT_EXT = {"txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "yaml", "yml", "xml", "html", "htm", "css", "js", "ts", "tsx", "jsx", "py", "rb", "go", "rs",
            "java", "c", "h", "cpp", "hpp", "cs", "php", "sh", "sql", "toml", "ini", "cfg", "conf", "log", "tex", "rst", "env.example"}


class UploadError(Exception):
    """A file that cannot be accepted, with a reason the person can act on."""


def save(ws: "Workspace", agent: str, name: str, data_b64: str) -> str:
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
    folder = ws.files_dir(agent) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    existing = [p for p in folder.iterdir() if p.is_file()]
    if len(existing) >= MAX_FILES or folder_size(ws.files_dir(agent)) + len(raw) > MAX_TOTAL:
        raise UploadError("this agent already holds as many uploaded files as allowed; delete some first")
    stem, dot, suffix = name.rpartition(".")
    target, n = folder / name, 1
    while target.exists():  # never overwrite
        n += 1
        target = folder / (f"{stem} ({n}).{suffix}" if dot else f"{name} ({n})")
    target.write_text(text, encoding="utf-8")
    ws.audit(agent, "file-uploaded", f"{target.name} {len(raw)} bytes")
    return f"uploads/{target.name}"


def read_for_download(ws: "Workspace", agent: str, relative: str) -> tuple[str, bytes]:
    ws.get_agent(agent)
    try:
        path = safe_path(ws.files_dir(agent), relative)
    except PathError as err:
        raise UploadError(str(err)) from None
    if not path.is_file() or path.stat().st_size > 5_000_000:
        raise UploadError("no such file (or it is too large to download here)")
    return path.name, path.read_bytes()
