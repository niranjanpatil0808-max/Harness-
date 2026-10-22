"""Per-agent secrets.

Secrets are handed to tools as environment variables BY NAME (the model only ever sees the names), and
every tool output is passed through `redact` so a value that gets printed is replaced by [secret:NAME].

At rest: if the optional `cryptography` package is installed, each agent's secrets are Fernet-encrypted
with a key kept in `keychain/.key` (mode 0600). Without it they are stored as plain JSON (mode 0600),
which is NOT encryption: it only keeps them out of the database and the model's prompts.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:  # optional dependency
    from cryptography.fernet import Fernet
except ImportError:  # pragma: no cover - exercised by tests through the `encrypt` switch
    Fernet = None

NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
MIN_REDACT_LENGTH = 4


def _write_private(path: Path, data: bytes) -> None:
    """Write a file that is never readable by other users, not even for a moment."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)  # also tightens a file that already existed


class Keychain:
    def __init__(self, folder: Path, encrypt: bool | None = None) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.encrypted = (Fernet is not None) if encrypt is None else (encrypt and Fernet is not None)
        self._fernet = None
        if self.encrypted:
            key_path = self.folder / ".key"
            if not key_path.exists():
                _write_private(key_path, Fernet.generate_key())
            self._fernet = Fernet(key_path.read_bytes())

    def _path(self, agent: str) -> Path:
        return self.folder / f"{agent}.json"

    def _load(self, agent: str) -> dict[str, str]:
        path = self._path(agent)
        if not path.exists():
            return {}
        raw = path.read_bytes()
        if self._fernet is not None and raw.startswith(b"gAAAA"):
            raw = self._fernet.decrypt(raw)
        return json.loads(raw)

    def _save(self, agent: str, secrets: dict[str, str]) -> None:
        raw = json.dumps(secrets).encode()
        if self._fernet is not None:
            raw = self._fernet.encrypt(raw)
        _write_private(self._path(agent), raw)

    def set(self, agent: str, name: str, value: str) -> None:
        if not NAME_RE.match(name):
            raise ValueError("secret names look like API_TOKEN (capital letters, digits, underscores)")
        if not value:
            raise ValueError("empty secret")
        secrets = self._load(agent)
        secrets[name] = value
        self._save(agent, secrets)

    def delete(self, agent: str, name: str) -> None:
        secrets = self._load(agent)
        secrets.pop(name, None)
        self._save(agent, secrets)

    def names(self, agent: str) -> list[str]:
        return sorted(self._load(agent))

    def env_for(self, agent: str, names: list[str]) -> dict[str, str]:
        """Environment variables for the requested secret names; unknown names raise KeyError."""
        secrets = self._load(agent)
        missing = [n for n in names if n not in secrets]
        if missing:
            raise KeyError(f"no such secret: {', '.join(missing)}")
        return {n: secrets[n] for n in names}

    def redact(self, agent: str, text: str) -> str:
        """Replace any stored secret value that appears in `text` with [secret:NAME]."""
        for name, value in self._load(agent).items():
            if len(value) >= MIN_REDACT_LENGTH:
                text = text.replace(value, f"[secret:{name}]")
        return text
