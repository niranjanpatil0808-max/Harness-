"""A small local HTTP server: a JSON API, one static page, and the web apps agents publish.

It binds to 127.0.0.1 by default. Every API call needs the access token (header `X-Token`); published
apps are served with a sandboxing Content-Security-Policy so they cannot reach the API.
"""

from __future__ import annotations

import hmac
import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import Workspace, WorkspaceError
from .sandbox import PathError, safe_path
from .scheduler import Scheduler

MAX_BODY = 64_000
WEB = Path(__file__).parent / "web"
APP_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; "
           "style-src 'unsafe-inline'; img-src data:")


def load_token(ws: Workspace) -> str:
    path = ws.root / "token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(24))
        path.chmod(0o600)
    return path.read_text().strip()


def make_server(ws: Workspace, host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> ThreadingHTTPServer:
    token = token or load_token(ws)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Kintsugi"

        def log_message(self, fmt, *args):  # keep the terminal quiet
            pass

        # --- helpers ---
        def _send(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data) -> None:
            self._send(status, json.dumps(data).encode())

        def _authorized(self, query: dict) -> bool:
            given = self.headers.get("X-Token") or (query.get("token") or [""])[0]
            return hmac.compare_digest(given.encode(), token.encode())

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise WorkspaceError("request too large")
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise WorkspaceError("the request body must be a JSON object")
            return data

        # --- routing ---
        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path in ("/", "/index.html"):
                return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
            if not self._authorized(query):
                return self._json(401, {"error": "missing or wrong access token"})
            try:
                if url.path.startswith("/apps/"):
                    return self._app(url.path)
                self._json(200, self._get(url.path, query))
            except (WorkspaceError, KeyError) as err:
                self._json(400, {"error": str(err)})

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorized(parse_qs(url.query)):
                return self._json(401, {"error": "missing or wrong access token"})
            try:
                self._json(200, self._post(url.path, self._body()))
            except (WorkspaceError, KeyError, ValueError) as err:  # json errors are ValueErrors too
                self._json(400, {"error": str(err)})

        def _get(self, path: str, query: dict):
            if path == "/api/state":
                return {"agents": [{k: a[k] for k in ("name", "persona", "tier", "tools")} for a in ws.list_agents()],
                        "rooms": [{**r, "members": ws.members(r["name"])} for r in ws.list_rooms()],
                        "approvals": ws.approvals(), "jobs": ws.list_jobs()}
            if path == "/api/messages":
                room = query["room"][0]
                return ws.history(room, after=int((query.get("after") or ["0"])[0]))
            if path == "/api/audit":
                return ws.audit_log()
            if path == "/api/files":
                agent = query["agent"][0]
                ws.get_agent(agent)
                base = ws.files_dir(agent)
                return sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())[:200]
            if path == "/api/lessons":
                from kintsugi.memory import MemoryStore

                ws.get_agent(query["agent"][0])
                store = MemoryStore.load(ws.lessons_path(query["agent"][0]))
                return [{"text": l.text, "uses": l.uses, "wins": l.wins, "status": l.status} for l in store.lessons]
            raise WorkspaceError("unknown endpoint")

        def _post(self, path: str, body: dict):
            if path == "/api/say":
                room = str(body["room"])
                sender = str(body.get("as") or "you")
                return {"id": ws.post(room, sender, str(body["text"]), human=True)}
            if path == "/api/agents":
                ws.create_agent(str(body["name"]), str(body.get("persona", "")), str(body.get("tier", "auto")))
                return {"ok": True}
            if path == "/api/rooms":
                ws.create_room(str(body["name"]), [str(m) for m in body.get("members", [])])
                return {"ok": True}
            if path == "/api/dm":
                return {"room": ws.open_dm(str(body["a"]), str(body["b"]))}
            if path == "/api/tier":
                ws.set_tier(str(body["agent"]), str(body["tier"]))
                return {"ok": True}
            if path == "/api/approve":
                return {"output": ws.decide(int(body["id"]), bool(body["approve"]), by="web")}
            if path == "/api/jobs":
                return {"id": ws.add_job(str(body["agent"]), str(body["room"]), str(body["cron"]), str(body["prompt"]))}
            if path == "/api/jobs/delete":
                ws.remove_job(int(body["id"]))
                return {"ok": True}
            raise WorkspaceError("unknown endpoint")

        def _app(self, path: str) -> None:
            parts = path.split("/")  # ['', 'apps', agent, app, ...rest]
            if len(parts) < 4 or ws.get_agent(parts[2], missing_ok=True) is None:
                return self._json(404, {"error": "no such app"})
            relative = "/".join(parts[3:]) or "index.html"
            if relative.endswith("/"):
                relative += "index.html"
            try:
                target = safe_path(ws.www_dir(parts[2]), relative)
            except PathError:
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
    print(f"Kintsugi workspace on http://{host}:{server.server_port}/")
    print(f"Access token (also saved in {ws.root / 'token'}): {server.token}")  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        scheduler.stop()
        server.server_close()
        ws.close()
