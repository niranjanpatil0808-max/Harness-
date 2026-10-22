"""A small local HTTP server: a JSON API, one static page, and the web apps agents publish.

It binds to 127.0.0.1 by default. Every API call needs the access token (header `X-Token`); published
apps are served with a sandboxing Content-Security-Policy so they cannot reach the API.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import sandbox
from .core import Workspace, WorkspaceError
from .keychain import _write_private
from .sandbox import PathError, safe_path
from . import core as core_mod
from .scheduler import Scheduler
from .team import Identity, TeamError, required_role
from .team import Identity, TeamError, required_role

MAX_BODY = 64_000
WEB = Path(__file__).parent / "web"
PAGE_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; worker-src 'self'; manifest-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
APP_LINK_SECONDS = 3600
MAX_FAILURES, FAILURE_WINDOW = 10, 60  # wrong tokens per client per minute before it is turned away
MIN_PUBLIC_TOKEN = 24
APP_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
           "style-src 'unsafe-inline'; img-src data:")


class RateLimited(Exception):
    """Too many requests from one person (HTTP 429)."""


class Forbidden(Exception):
    """The caller is who they say they are but is not allowed to do this (HTTP 403)."""


def web_version() -> str:
    """A short hash of the interface files: a new build gets a new service-worker cache, so phones update."""
    digest = hashlib.sha256()
    for path in sorted(WEB.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(WEB).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def load_token(ws: Workspace) -> str:
    """KINTSUGI_TOKEN if set (handy for Codespaces secrets), else a random one kept in the workspace folder."""
    env = os.environ.get("KINTSUGI_TOKEN", "").strip()
    if env:
        return env
    path = ws.root / "token"
    if not path.exists():
        _write_private(path, secrets.token_urlsafe(24).encode())
    return path.read_text().strip()


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def _lessons(ws: Workspace, agent: str) -> list[dict]:
    from kintsugi.memory import MemoryStore

    store = MemoryStore.load(ws.lessons_path(agent))
    return [{"text": l.text, "uses": l.uses, "wins": l.wins, "status": l.status} for l in store.lessons]


def _apps(ws: Workspace, agent: str) -> list[str]:
    base = ws.www_dir(agent)
    return sorted(p.name for p in base.iterdir() if (p / "index.html").is_file()) if base.is_dir() else []


def make_server(ws: Workspace, host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> ThreadingHTTPServer:
    token = token or load_token(ws)
    if not is_loopback(host) and len(token) < MIN_PUBLIC_TOKEN:
        raise SystemExit(f"Refusing to listen on {host}: when the workspace is reachable from a network, KINTSUGI_TOKEN "
                         f"must be a long random string (at least {MIN_PUBLIC_TOKEN} characters).")
    failures: dict[str, list[float]] = {}
    failure_lock = threading.Lock()
    sent_times: dict[str, list[float]] = {}
    trust_proxy = os.environ.get("KINTSUGI_TRUST_PROXY") == "1"

    def sign(agent: str, app: str, expires: int) -> str:
        return hmac.new(token.encode(), f"{agent}/{app}/{expires}".encode(), hashlib.sha256).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        server_version = "Kintsugi"
        timeout = 30  # seconds a connection may sit idle or send slowly before it is dropped

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        # --- helpers ---
        def _send(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if "Content-Security-Policy" not in (extra or {}):
                self.send_header("X-Frame-Options", "DENY")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode())

        def _client(self) -> str:
            if trust_proxy:  # behind a hosting platform's proxy the real client is the last forwarded address
                forwarded = self.headers.get("X-Forwarded-For", "")
                if forwarded:
                    return forwarded.split(",")[-1].strip()
            return self.client_address[0]

        def _authorized(self, query: dict = None) -> bool:
            """Check the access token (header only, never the URL). Clients with many wrong tries are turned away."""
            client, now = self._client(), time.time()
            given = self.headers.get("X-Token") or ""
            who = ws.team.identify(given, token)  # a RIGHT token always works: guessing is throttled, not logging in
            if who is not None:
                self.who = who
                if self.headers.get("X-Visible", "1") == "1":  # a hidden tab does not count as "looking at it"
                    ws.touch(who.name)
                return True
            with failure_lock:
                recent = [t for t in failures.get(client, []) if now - t < FAILURE_WINDOW]
                failures[client] = recent
                if len(recent) >= MAX_FAILURES:
                    return False
                failures[client].append(now)
                if len(failures) > 5000:  # never let the table itself grow without bound
                    failures.clear()
            return False

        def _app_link_ok(self, parts: list[str], query: dict) -> bool:
            """A published app is opened with a link that expires and works for that one app only."""
            try:
                expires, signature = int((query.get("exp") or ["0"])[0]), (query.get("sig") or [""])[0]
            except ValueError:
                return False
            return (len(parts) >= 4 and expires > time.time()
                    and hmac.compare_digest(signature.encode(), sign(parts[2], parts[3], expires).encode()))  # bytes: a non-ASCII signature must not crash

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0 or length > MAX_BODY:
                raise WorkspaceError("request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise WorkspaceError("the request body must be a JSON object")
            return data

        # --- routing ---
        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/healthz":  # for hosting platforms; reveals nothing
                return self._json(200, {"ok": True})
            if url.path == "/manifest.webmanifest":
                return self._send(200, (WEB / "manifest.webmanifest").read_bytes(), "application/manifest+json")
            if url.path == "/sw.js":  # served from the root so it can control the whole app
                body = (WEB / "sw.js").read_bytes().replace(b"__VERSION__", web_version().encode())
                return self._send(200, body, "text/javascript; charset=utf-8", {"Service-Worker-Allowed": "/", "X-Frame-Options": "DENY"})
            if url.path in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8",
                                  {"Content-Security-Policy": PAGE_CSP, "X-Frame-Options": "DENY"})
            if url.path.startswith("/apps/"):
                if not (self._app_link_ok(url.path.split("/"), query) or self._authorized()):
                    return self._json(401, {"error": "this app link is missing, wrong or expired; open it from the workspace"})
                return self._guard(lambda: self._app(url.path))
            if url.path.startswith("/static/"):  # the page's own scripts and styles; public, read-only
                return self._static(url.path[len("/static/"):])
            if not self._authorized():
                return self._json(401, {"error": "missing or wrong access token"})
            self._guard(lambda: self._json(200, self._get(url.path, query)), url.path)

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/join":  # the one call that needs no token: an invite code turns into a person
                return self._guard(lambda: self._json(200, self._join(self._body())))
            if not self._authorized():
                return self._json(401, {"error": "missing or wrong access token"})
            self._guard(lambda: self._json(200, self._post(url.path, self._body())), url.path)

        def _rate_limit(self, name: str, limit: int = 30, window: float = 60.0) -> None:
            """One person cannot spend the whole team's model quota with a flood of messages."""
            now = time.time()
            with failure_lock:
                recent = [t for t in sent_times.get(name, []) if now - t < window]
                if len(recent) >= limit:
                    sent_times[name] = recent
                    raise RateLimited(f"slow down: at most {limit} messages a minute")
                recent.append(now)
                sent_times[name] = recent

        def _known_name(self, name: str) -> None:
            if not (ws.get_agent(name, missing_ok=True) or ws.team.is_person(name)):
                raise WorkspaceError(f"'{name}' is not an agent or a person in this workspace")

        def _owns_job(self, job_id: int) -> None:
            job = next((j for j in ws.list_jobs() if j["id"] == job_id), None)
            if job is None:
                raise WorkspaceError("no such job")
            if not ws.team.can_see_room(self.who, job["room"]):
                raise Forbidden("you are not in that room")
            if not self.who.at_least("admin") and job["owner"] != self.who.name:
                raise Forbidden("that schedule belongs to someone else")

        def _may_use_room(self, room: str, agent: str) -> None:
            if not ws.team.can_see_room(self.who, room):
                raise Forbidden("you are not in that room")
            if agent not in ws.members(room) and ws._require_room(room)["kind"] != "dm":
                raise WorkspaceError(f"{agent} is not in that room")

        def _join(self, body: dict) -> dict:
            """Public endpoint: redeem an invite. Wrong codes count against the same per-client throttle as wrong tokens."""
            client, now = self._client(), time.time()
            with failure_lock:
                recent = [t for t in failures.get(client, []) if now - t < FAILURE_WINDOW]
                failures[client] = recent
                if len(recent) >= MAX_FAILURES:
                    raise Forbidden("too many tries; wait a minute")
            try:
                return ws.team.join(str(body.get("code", "")), str(body.get("name", "")))
            except TeamError:
                with failure_lock:
                    failures.setdefault(client, []).append(now)
                raise

        def _guard(self, action, path: str | None = None) -> None:
            """Turn every failure into a JSON error: 403 when the role is not enough, 400 for bad requests, 500 (and an audit entry) for bugs."""
            try:
                if path is not None and not self.who.at_least(required_role(path)):
                    raise Forbidden(f"your role ({self.who.role}) cannot do this")
                action()
            except Forbidden as err:
                self._json(403, {"error": str(err)})
            except RateLimited as err:
                self._json(429, {"error": str(err)})
            except (TeamError, WorkspaceError, PathError, ValueError, KeyError, TypeError) as err:  # json errors are ValueErrors
                message = f"missing field: {err}" if isinstance(err, KeyError) else str(err)
                self._json(400, {"error": message})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as err:  # never drop the connection without an answer
                ws.audit(None, "server-error", f"{type(err).__name__}: {err}")
                self._json(500, {"error": "internal error (see the audit log)"})

        def _get(self, path: str, query: dict):
            if path == "/api/state":
                # newest message per room, and newest one written by someone other than the reader: that drives "unread"
                who = self.who
                latest = {row["room"]: {"last_id": row["last_id"], "last_other": row["last_other"] or 0} for row in ws.db.query(
                    "SELECT room, MAX(id) AS last_id, MAX(CASE WHEN sender != ? THEN id END) AS last_other FROM messages GROUP BY room", (who.name,))}
                rooms = [r for r in ws.list_rooms() if ws.team.can_see_room(who, r["name"])]
                seen = {r["name"] for r in rooms}
                approvals = [{**a, "can_decide": ws.team.can_decide(who, a)} for a in ws.approvals() if a["room"] in seen or who.role == "owner"]
                approvals = [a for a in approvals if a["can_decide"] or a.get("requested_by") == who.name]
                jobs = ws.list_jobs() if who.at_least("admin") else [j for j in ws.list_jobs() if j["room"] in seen]
                return {"me": {"name": who.name, "role": who.role}, "approval_policy": ws.team.policy(),
                        "people": [u["name"] for u in ws.team.users()] if who.at_least("admin") else [],
                        "agents": [{**{k: a[k] for k in ("name", "persona", "tier", "tools", "model", "provider", "internet", "playbook")},
                                    "secrets": ws.keychain.names(a["name"]) if who.at_least("admin") else [], "apps": _apps(ws, a["name"]), "plugins": ws.plugins.enabled_for(a["name"]),
                                    "integrations": ws.integrations.enabled_for(a["name"])}
                                   for a in ws.list_agents()],
                        "rooms": [{**r, "members": ws.members(r["name"]), **latest.get(r["name"], {"last_id": 0, "last_other": 0})} for r in rooms],
                        "approvals": approvals, "jobs": jobs, "busy": ws.busy(),
                        "sandbox": sandbox.status(), "provider": ws.provider(), "search_configured": ws.search_settings()["configured"], "internet_enabled": ws.internet_settings()["enabled"],
                        "providers": [{"id": p["id"], "label": p["label"], "model": p["model"], "default": p["default"]} for p in ws.providers()["profiles"]] if who.at_least("admin") else [],
                        "model_ready": bool(ws.providers()["profiles"]) or ws.providers()["env_fallback"] or ws.model_factory is not core_mod.default_model_factory,
                        "improve": {k: v for k, v in ws.improver.status().items() if k != "last"},
                        "usage": {"calls": ws.calls_today(), "limit": ws.daily_calls}}
            if path == "/api/messages":
                room = query["room"][0]
                if not ws.team.can_see_room(self.who, room):
                    raise Forbidden("you are not in that room")
                return ws.history(room, after=int((query.get("after") or ["0"])[0]))
            if path == "/api/audit":
                rows = ws.audit_log()
                if self.who.role != "owner":  # tool arguments can hold private chat content: admins see what happened, not the content
                    rows = [{**r, "detail": (r["detail"] or "").split(" ", 1)[0] if r["event"] in ("tool-ok", "tool-error", "approval-granted", "approval-requested", "approval-denied") else r["detail"]} for r in rows]
                return rows
            if path == "/api/me":
                return {"name": self.who.name, "role": self.who.role}
            if path == "/api/team":
                return {"users": ws.team.users(), "invites": ws.team.invites(), "policy": ws.team.policy(),
                        "rooms": [r["name"] for r in ws.list_rooms() if r["kind"] == "room"]}
            if path == "/api/files":
                agent = query["agent"][0]
                ws.get_agent(agent)
                base = ws.files_dir(agent)
                return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())[:200]
            if path == "/api/push":
                from . import push

                return {"available": push.available(), "public_key": ws.pusher.public_key() if push.available() else None, "devices": ws.pusher.count()}
            if path == "/api/automations":
                from . import automations

                mine = [j for j in automations.listing(ws) if self.who.at_least("admin") or j["owner"] == self.who.name]
                return {"jobs": mine, "timezone": ws.get_timezone(), "search": ws.search_settings()["configured"],
                        "server_time": ws.local_datetime(ws.clock()).strftime("%Y-%m-%d %H:%M")}
            if path == "/api/timezone":
                now = ws.local_datetime(ws.clock())
                return {**ws.get_timezone(), "now": now.strftime("%Y-%m-%d %H:%M")}
            if path == "/api/search":
                from .websearch import PROVIDERS

                return {**ws.search_settings(), "used_today": ws.searches_today(),
                        "providers": {k: {kk: v[kk] for kk in ("label", "signup", "note")} for k, v in PROVIDERS.items()}}
            if path == "/api/backup":
                return ws.backups.status()
            if path == "/api/providers":
                return ws.providers()
            if path == "/api/internet":
                return ws.internet_settings()
            if path == "/api/integrations":
                return {"items": ws.integrations.status(), "agents": [a["name"] for a in ws.list_agents()]}
            if path == "/api/plugins":
                from .plugin_examples import EXAMPLES

                return {"plugins": ws.plugins.listing(), "examples": EXAMPLES}
            if path == "/api/parallel":
                return {"limit": ws.parallel_limit(), "max": ws.MAX_PARALLEL, "busy": ws.busy()}
            if path == "/api/tone":
                from .core import TONE_LABELS, TONES

                return {**ws.get_tone(self.who.name), "labels": TONE_LABELS, "examples": TONES}
            if path == "/api/improve":
                imp = ws.improver
                return {"settings": imp.settings(), "status": imp.status(), "studies": imp.studies(),
                        "proposals": imp.proposals("pending") + [p for p in imp.proposals(limit=30) if p["status"] != "pending"]}
            if path == "/api/improve/study":
                return {"report": ws.improver.study_report(int(query["id"][0]))}
            if path == "/api/improve/models":  # the model names your provider says this key can use
                from .core import default_model_factory

                if ws.model_factory is not default_model_factory and ws.study_model_factory is None:
                    return {"models": []}
                try:
                    probe = ws.study_model(None)
                    return {"models": probe.list_models() if hasattr(probe, "list_models") else []}
                except RuntimeError as err:
                    raise WorkspaceError(str(err))
                except OSError as err:
                    raise WorkspaceError(f"could not reach the provider: {err}")
            if path == "/api/applink":
                agent, app = query["agent"][0], query["app"][0]
                if ws.get_agent(agent, missing_ok=True) is None or app not in _apps(ws, agent):
                    raise WorkspaceError("no such app")
                expires = int(time.time()) + APP_LINK_SECONDS
                return {"url": f"/apps/{agent}/{app}/?exp={expires}&sig={sign(agent, app, expires)}"}
            if path == "/api/export":  # everything except secret values, as one JSON document
                return {"agents": [{k: a[k] for k in ("name", "persona", "tier", "tools")} for a in ws.list_agents()],
                        "rooms": [{**r, "members": ws.members(r["name"]), "messages": ws.history(r["name"], limit=100000)}
                                  for r in ws.list_rooms()],
                        "notes": ws.db.query("SELECT agent, text, ts FROM notes"), "jobs": ws.list_jobs(),
                        "improvement": {"settings": ws.improver.settings(), "proposals": ws.improver.proposals(limit=200),
                                        "studies": ws.improver.studies(50)},
                        "lessons": {a["name"]: _lessons(ws, a["name"]) for a in ws.list_agents()}}
            if path == "/api/file":
                agent = query["agent"][0]
                ws.get_agent(agent)
                target = safe_path(ws.files_dir(agent), query["path"][0])
                if not target.is_file():
                    raise WorkspaceError("no such file")
                return {"path": query["path"][0], "text": target.read_text(errors="replace")[:100_000]}
            if path == "/api/lessons":
                ws.get_agent(query["agent"][0])
                return _lessons(ws, query["agent"][0])
            raise WorkspaceError("unknown endpoint")

        def _post(self, path: str, body: dict):
            if path == "/api/say":
                self._rate_limit(self.who.name)
                room = str(body["room"])
                if self.who.role == "owner":
                    sender = str(body.get("as") or "you")
                else:  # a person can only speak as themselves, and only in rooms they belong to
                    if not ws.team.can_see_room(self.who, room):
                        raise Forbidden("you are not in that room")
                    sender = self.who.name
                return {"id": ws.post(room, sender, str(body["text"]), human=True)}
            if path == "/api/agents":
                if str(body.get("tier", "auto")) == "dangerous" and self.who.role != "owner":
                    raise Forbidden("only the owner can create an agent that never asks")
                ws.create_agent(str(body["name"]), str(body.get("persona", "")), str(body.get("tier", "auto")))
                return {"ok": True}
            if path == "/api/rooms":
                members = [str(m) for m in body.get("members", [])]
                for m in members + [self.who.name]:
                    self._known_name(m)
                ws.create_room(str(body["name"]), list(dict.fromkeys(members + [self.who.name])))
                return {"ok": True}
            if path == "/api/team/invite":
                made = ws.team.create_invite(self.who, str(body.get("role", "member")), body.get("rooms"), float(body.get("days", 7)))
                return made
            if path == "/api/team/revoke-invite":
                ws.team.revoke_invite(str(body["id"]))
                return {"ok": True}
            if path == "/api/team/remove":
                ws.team.remove(self.who, str(body["name"]))
                return {"ok": True}
            if path == "/api/team/role":
                ws.team.set_role(str(body["name"]), str(body["role"]))
                return {"ok": True}
            if path == "/api/team/policy":
                return {"policy": ws.team.set_policy(str(body["policy"]))}
            if path == "/api/me/token":
                if self.who.role == "owner":
                    raise WorkspaceError("the owner's token is changed by setting KINTSUGI_TOKEN, not here")
                return {"token": ws.team.rotate_token(self.who.name)}
            if path == "/api/room/members":
                room = str(body["room"])
                if ws._require_room(room)["kind"] != "room":
                    raise WorkspaceError("people are added to shared rooms, not direct chats")
                for m in body.get("add", []):
                    self._known_name(str(m))
                    ws.add_member(room, str(m))
                for m in body.get("remove", []):
                    if str(m) == "you":
                        raise WorkspaceError("the owner stays in every room")
                    ws.remove_member(room, str(m))
                ws.audit(None, "room-members", f"{room} +{body.get('add', [])} -{body.get('remove', [])} by {self.who.name}")
                return {"members": ws.members(room)}
            if path == "/api/dm":
                a = str(body["a"]) if self.who.role == "owner" else self.who.name  # a person opens only their own direct chats
                self._known_name(str(body["b"]))
                return {"room": ws.open_dm(a, str(body["b"]))}
            if path == "/api/persona":
                ws.set_persona(str(body["agent"]), str(body["persona"]))
                return {"ok": True}
            if path == "/api/secret":  # the value goes to the keychain only; it is never sent back or shown
                ws.get_agent(str(body["agent"]))
                ws.keychain.set(str(body["agent"]), str(body["name"]), str(body["value"]))
                ws.audit(str(body["agent"]), "secret-set", str(body["name"]))
                return {"ok": True}
            if path == "/api/secret/delete":
                ws.get_agent(str(body["agent"]))
                ws.keychain.delete(str(body["agent"]), str(body["name"]))
                ws.audit(str(body["agent"]), "secret-deleted", str(body["name"]))
                return {"ok": True}
            if path == "/api/agent/delete":
                ws.delete_agent(str(body["name"]))
                return {"ok": True}
            if path == "/api/room/delete":
                if ws._require_room(str(body["name"]))["kind"] == "dm" and self.who.role != "owner":
                    raise Forbidden("only the owner can delete a private chat")
                ws.delete_room(str(body["name"]))
                return {"ok": True}
            if path == "/api/purge":
                return {"deleted": ws.purge_messages(float(body["days"]))}
            if path == "/api/automations":
                from . import automations

                when = {"time": body.get("time"), "days": body.get("days", "daily")} if body.get("time") else None
                self._may_use_room(str(body["room"]), str(body["agent"]))
                return automations.create(ws, str(body["kind"]), str(body["agent"]), str(body["room"]), body, when, owner=self.who.name)
            if path == "/api/push/subscribe":
                ws.pusher.subscribe(str(body["endpoint"]), self.who.name)
                return {"devices": ws.pusher.count()}
            if path == "/api/push/unsubscribe":
                ws.pusher.unsubscribe(str(body["endpoint"]))
                return {"devices": ws.pusher.count()}
            if path == "/api/push/test":
                return {"delivered": ws.pusher.notify("test", force=True, users=[self.who.name])}
            if path == "/api/automations/toggle":
                self._owns_job(int(body["id"]))
                ws.set_job_enabled(int(body["id"]), bool(body["enabled"]))
                return {"ok": True}
            if path == "/api/automations/run":
                self._owns_job(int(body["id"]))
                return {"message": ws.run_job_now(int(body["id"]))}
            if path == "/api/timezone":
                if not self.who.at_least("admin"):
                    raise Forbidden("only an admin can change the workspace time zone")
                return ws.set_timezone(str(body.get("name", "")), int(body.get("offset_minutes", 0)))
            if path == "/api/search/settings":  # the key is write-only: it is never returned by any endpoint
                return ws.set_search(str(body["provider"]), str(body.get("key") or "") or None, body.get("daily_cap"))
            if path == "/api/search/test":
                from .websearch import SearchError

                try:
                    results = ws.web_search(str(body.get("query") or "open source software"), 3)
                except SearchError as err:
                    raise WorkspaceError(str(err))
                return {"results": results}
            if path == "/api/search/remove":
                ws.remove_search_key()
                return {"ok": True}
            if path.startswith("/api/integrations/"):
                from .integrations import IntegrationError

                try:
                    action, kind = path.rsplit("/", 1)[1], str(body.get("kind", ""))
                    if action == "save":  # credentials are write-only: nothing here or anywhere returns them
                        return ws.integrations.save(kind, {k: v for k, v in body.items() if k != "kind"})
                    if action == "remove":
                        ws.integrations.remove(kind)
                        return {"ok": True}
                    if action == "enable":
                        ws.integrations.set_enabled(str(body["agent"]), kind, bool(body.get("on")))
                        return {"ok": True}
                    if action == "test":
                        try:
                            ws.spend_fetch()
                            return {"ok": True, "message": ws.integrations.test(kind)}
                        except IntegrationError as err:
                            return {"ok": False, "error": ws.keychain.redact("_workspace", str(err))}
                except IntegrationError as err:
                    raise WorkspaceError(str(err)) from None
            if path.startswith("/api/plugins/"):
                from .plugins import PluginError

                try:
                    action = path.rsplit("/", 1)[1]
                    source = {k: body[k] for k in ("github", "manifest") if k in body}
                    if action == "preview":
                        return ws.plugins.preview(source)
                    if action == "install":
                        agents_on = [a["name"] for a in ws.list_agents()] if body.get("enable_for") == "all" else [str(a) for a in body.get("enable_for") or []]
                        return ws.plugins.install(source, str(body.get("fingerprint", "")), agents_on)
                    if action == "uninstall":
                        ws.plugins.uninstall(str(body["id"]))
                        return {"ok": True}
                    if action == "enable":
                        ws.plugins.set_enabled(str(body["agent"]), str(body["id"]), bool(body.get("on")))
                        return {"ok": True}
                except PluginError as err:
                    raise WorkspaceError(str(err)) from None
            if path == "/api/parallel":
                return {"limit": ws.set_parallel(int(body["limit"])), "max": ws.MAX_PARALLEL}
            if path == "/api/internet":
                return ws.set_internet(body.get("enabled"), body.get("fetch_cap"))
            if path == "/api/agent/internet":
                ws.set_agent_internet(str(body["agent"]), str(body["mode"]))
                return {"ok": True}
            if path == "/api/providers/save":  # the key is write-only: no endpoint ever returns it
                return ws.set_provider(str(body["id"]), str(body["kind"]), str(body["base_url"]), str(body.get("model") or ""),
                                       str(body.get("key") or "") or None, str(body.get("label") or ""), bool(body.get("keyless")), bool(body.get("make_default")))
            if path == "/api/providers/remove":
                return ws.remove_provider(str(body["id"]))
            if path == "/api/providers/default":
                return ws.set_default_provider(str(body["id"]))
            if path == "/api/providers/test":
                return ws.test_provider(str(body["id"]), str(body.get("model") or "") or None)
            if path == "/api/backup/run":
                if not ws.backups.start(force=True):
                    raise WorkspaceError("a backup is already running")
                return {"started": True}
            if path == "/api/tone":
                return ws.set_tone(self.who.name, str(body["style"]), str(body.get("custom", "")))
            if path == "/api/improve/settings":
                if (body.get("share_lessons") or body.get("auto_apply")) and self.who.role != "owner":
                    raise Forbidden("only the owner can turn on sharing lessons with the provider or applying changes automatically")
                return ws.improver.update_settings(body)
            if path == "/api/improve/run":
                kind = str(body.get("kind", "all"))
                try:
                    ws.study_model(None)  # fail now, with a clear message, if there is no model key
                except RuntimeError as err:
                    raise WorkspaceError(str(err))
                return {"started": ws.improver.start(kind)}
            if path == "/api/improve/decide":
                return ws.improver.decide(int(body["id"]), bool(body["accept"]), by="web")
            if path == "/api/improve/revert":
                return {"reverted": ws.improver.revert(str(body["agent"]), str(body["kind"]))}
            if path == "/api/agent/model":
                ws.set_model(str(body["agent"]), str(body.get("model") or "") or None, str(body.get("provider") or "") or None)
                return {"ok": True}
            if path == "/api/agent/playbook":
                from .improve import clean_playbook

                text = str(body.get("playbook", ""))
                cleaned = clean_playbook(text)
                if text.strip() and not cleaned:
                    raise WorkspaceError("no acceptable rules: write short rules that each start with '- ' and are about using "
                                         "tools (rules about permissions, secrets, links or safety are removed)")
                ws.set_playbook(str(body["agent"]), cleaned)
                return {"playbook": cleaned}
            if path == "/api/tier":
                if str(body.get("tier")) == "dangerous" and self.who.role != "owner":
                    raise Forbidden("only the owner can switch an agent to 'never ask'")
                ws.set_tier(str(body["agent"]), str(body["tier"]))
                return {"ok": True}
            if path == "/api/approve":
                row = ws.db.one("SELECT * FROM approvals WHERE id = ?", (int(body["id"]),))
                if row is None:
                    raise WorkspaceError("no such approval")
                if not ws.team.can_decide(self.who, row):
                    raise Forbidden("you are not allowed to decide this one (ask an admin, or see the approval policy in Settings > Team)")
                return {"output": ws.decide(int(body["id"]), bool(body["approve"]), by=self.who.name)}
            if path == "/api/jobs":
                self._may_use_room(str(body["room"]), str(body["agent"]))
                return {"id": ws.add_job(str(body["agent"]), str(body["room"]), str(body["cron"]), str(body["prompt"]), owner=self.who.name)}
            if path == "/api/jobs/delete":
                self._owns_job(int(body["id"]))
                ws.remove_job(int(body["id"]))
                return {"ok": True}
            raise WorkspaceError("unknown endpoint")

        def _static(self, relative: str) -> None:
            try:
                target = safe_path(WEB, relative)
            except PathError:
                return self._json(404, {"error": "not found"})
            if not target.is_file() or target.name == "index.html":
                return self._json(404, {"error": "not found"})
            ctype = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png"}.get(
                target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), ctype + "; charset=utf-8" if ctype.startswith("text") else ctype)

        def _app(self, path: str) -> None:
            parts = path.split("/")  # ['', 'apps', agent, app, ...rest]
            if len(parts) < 4 or ws.get_agent(parts[2], missing_ok=True) is None:
                return self._json(404, {"error": "no such app"})
            relative = "/".join(parts[3:]) or "index.html"
            if relative.endswith("/"):
                relative += "index.html"
            try:
                target = safe_path(ws.www_dir(parts[2]), relative)
                app_root = safe_path(ws.www_dir(parts[2]), parts[3])
            except PathError:
                return self._json(404, {"error": "no such app"})
            if app_root not in target.parents and target != app_root:  # a link for one app never reaches another
                return self._json(404, {"error": "no such app"})
            if target.is_dir():
                target = target / "index.html"
            if not target.is_file():
                return self._json(404, {"error": "no such app"})
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype == "text/html":  # only HTML can run script; serve everything inside the sandbox policy
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype, {"Content-Security-Policy": APP_CSP})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.token = token  # type: ignore[attr-defined]
    return server


def serve(ws: Workspace, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = make_server(ws, host, port)
    scheduler = Scheduler(ws)
    scheduler.start()
    info = sandbox.status()
    if is_loopback(host):
        print(f"Kintsugi workspace is running.\n  Open: http://{host}:{server.server_port}/#token={server.token}")  # type: ignore[attr-defined]
        print(f"  (the access token is also saved in {ws.root / 'token'}; set KINTSUGI_TOKEN to choose your own)")
    else:
        print(f"Kintsugi workspace is listening on {host}:{server.server_port}. Open your service's address and sign in "
              "with the KINTSUGI_TOKEN you set. (The token is not printed here.)")
    print(f"  Code sandbox: {info['backend']}" + ("" if info["isolated"] else
          " (NOT isolated: approved code runs with this program's permissions. Set KINTSUGI_SANDBOX=require to disable it.)"))
    print(f"  Conversations are sent to: {ws.provider()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        server.server_close()
        ws.close()
