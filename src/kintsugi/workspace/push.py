"""Web Push notifications, without putting your messages in them.

The server tells your phone's push service (Google, Apple or Mozilla) "wake this device", signed with a key only this
workspace holds (VAPID). The notification carries NO text: the app's service worker shows a generic "You have something
new". So the push companies learn that you got a notification, not what it says. A push is sent only when something
happened that needs you (an agent wrote, an approval is waiting) and you have not been using the app for a minute, and never
more than one a minute.

Needs the optional `cryptography` package (pip install "kintsugi[push]"). Without it, push is switched off and says so.
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

try:  # optional dependency
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
except ImportError:  # pragma: no cover - exercised through available()
    hashes = serialization = ec = decode_dss_signature = None

# Only the real push services may be called: a forged "subscription" must not turn the server into a request cannon.
PUSH_HOSTS = ("fcm.googleapis.com", ".push.apple.com", "push.apple.com", ".push.services.mozilla.com", "updates.push.services.mozilla.com",
              ".notify.windows.com")
MIN_SECONDS_BETWEEN_PUSHES = 60
ACTIVE_SECONDS = 90  # the user counts as "here" if the app talked to the server this recently
MAX_SUBSCRIPTIONS = 20
KEY_NAME = "VAPID_PRIVATE"


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def available() -> bool:
    return ec is not None


def endpoint_ok(endpoint: str) -> bool:
    """Is this URL one of the real push services (https, known host, no credentials, sane length)?"""
    if len(endpoint) > 600:
        return False
    parsed = urllib.parse.urlparse(endpoint)
    if os.environ.get("KINTSUGI_PUSH_ALLOW_LOCAL") == "1" and parsed.hostname == "127.0.0.1":  # tests only
        return parsed.scheme == "http"
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password or (parsed.port not in (None, 443)):
        return False
    return any(host == suffix.lstrip(".") or (suffix.startswith(".") and host.endswith(suffix)) for suffix in PUSH_HOSTS)


class Push:
    def __init__(self, ws: "Workspace") -> None:
        self.ws = ws
        self._lock = threading.Lock()
        self._last_sent = 0.0

    # --- the workspace's own signing key ---------------------------------------

    def _private_key(self):
        if not available():
            raise RuntimeError("push needs the 'cryptography' package")
        keychain = self.ws.keychain
        if KEY_NAME not in keychain.names(keychain_slot()):
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
            keychain.set(keychain_slot(), KEY_NAME, pem)
        pem = keychain.env_for(keychain_slot(), [KEY_NAME])[KEY_NAME]
        return serialization.load_pem_private_key(pem.encode(), password=None)

    def public_key(self) -> str:
        """The key the browser needs to subscribe (the 'application server key'), base64url."""
        point = self._private_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return b64u(point)

    def jwt(self, endpoint: str, now: float | None = None) -> str:
        parsed = urllib.parse.urlparse(endpoint)
        claims = {"aud": f"{parsed.scheme}://{parsed.netloc}", "exp": int((time.time() if now is None else now) + 12 * 3600),
                  "sub": os.environ.get("KINTSUGI_PUSH_SUBJECT", "https://github.com/niranjanpatil0808-max/KINTSUGI")}
        signing = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "." + \
            b64u(json.dumps(claims, separators=(",", ":")).encode())
        der = self._private_key().sign(signing.encode(), ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        return signing + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    # --- subscriptions ------------------------------------------------------------

    def subscribe(self, endpoint: str, user: str = "you") -> None:
        from .core import WorkspaceError

        if not available():
            raise WorkspaceError("push notifications are not available on this server (it needs the 'cryptography' package)")
        if not endpoint_ok(str(endpoint)):
            raise WorkspaceError("that is not a push address from a known push service")
        if self.ws.db.one("SELECT COUNT(*) AS n FROM push_subs")["n"] >= MAX_SUBSCRIPTIONS and not self.ws.db.one("SELECT 1 FROM push_subs WHERE endpoint = ?", (endpoint,)):
            raise WorkspaceError(f"at most {MAX_SUBSCRIPTIONS} devices can receive notifications")
        self.ws.db.execute("INSERT INTO push_subs (endpoint, user, created) VALUES (?, ?, ?) ON CONFLICT(endpoint) DO NOTHING", (endpoint, user, self.ws.clock()))
        self.ws.audit(None, "push-subscribed", urllib.parse.urlparse(endpoint).hostname or "")

    def unsubscribe(self, endpoint: str) -> None:
        self.ws.db.execute("DELETE FROM push_subs WHERE endpoint = ?", (endpoint,))
        self.ws.audit(None, "push-unsubscribed")

    def count(self) -> int:
        return self.ws.db.one("SELECT COUNT(*) AS n FROM push_subs")["n"]

    # --- sending ----------------------------------------------------------------------

    def send_one(self, endpoint: str) -> str:
        """Ask the push service to wake one device. Returns 'ok', 'gone' (remove it) or 'failed'. Never sends any text."""
        if not endpoint_ok(endpoint):
            return "gone"
        request = urllib.request.Request(endpoint, data=b"", method="POST", headers={
            "Authorization": f"vapid t={self.jwt(endpoint)}, k={self.public_key()}", "TTL": "3600", "Urgency": "normal", "Content-Length": "0"})
        try:
            with urllib.request.urlopen(request, timeout=10):
                return "ok"
        except urllib.error.HTTPError as err:
            return "gone" if err.code in (404, 410) else "failed"
        except (urllib.error.URLError, OSError, TimeoutError):
            return "failed"

    def notify(self, reason: str, force: bool = False) -> int:
        """Wake every subscribed device (at most once a minute unless `force`). Returns how many accepted it."""
        if not available() or self.count() == 0:
            return 0
        with self._lock:
            now = time.time()
            if not force and now - self._last_sent < MIN_SECONDS_BETWEEN_PUSHES:
                return 0
            self._last_sent = now
        delivered = 0
        for row in self.ws.db.query("SELECT endpoint FROM push_subs"):
            result = self.send_one(row["endpoint"])
            if result == "gone":
                self.ws.db.execute("DELETE FROM push_subs WHERE endpoint = ?", (row["endpoint"],))
            delivered += result == "ok"
        self.ws.audit(None, "push-sent", f"{reason}: {delivered} device(s)")
        return delivered


def keychain_slot() -> str:
    return "_workspace"
