import base64
import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kintsugi.model import MockModel
from kintsugi.workspace import backup
from kintsugi.workspace.core import Workspace
from kintsugi.workspace.server import make_server

PASS = "correct horse battery staple"


class FakeGitHub:
    """Just enough of api.github.com: one repo, one contents file."""

    def __init__(self, private=True, reject=False):
        self.private, self.reject, self.files, self.requests = private, reject, {}, []
        self.commit_date = None  # ISO time the fake says the backup file was last committed
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, payload, raw=None):
                data = raw if raw is not None else json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _route(self, method):
                outer.requests.append((method, self.path, self.headers.get("Authorization")))
                if outer.reject:
                    return self._send(403, {})
                parts = self.path.split("/", 5)  # '', repos, owner, repo, 'contents', path
                if len(parts) == 4:
                    return self._send(200, {"private": outer.private})
                if parts[4].startswith("commits"):  # the newest commit of the backup file
                    if outer.commit_date is None:
                        return self._send(404, {})
                    return self._send(200, [{"commit": {"committer": {"date": outer.commit_date}}}])
                path = parts[5]
                if method == "GET":
                    if path not in outer.files:
                        return self._send(404, {})
                    blob = outer.files[path]
                    if "raw" in (self.headers.get("Accept") or ""):
                        return self._send(200, None, raw=blob)
                    return self._send(200, {"sha": "abc"})
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.files[path] = base64.b64decode(body["content"])
                self._send(200, {})

            def do_GET(self):
                self._route("GET")

            def do_PUT(self):
                self._route("PUT")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def make_ws(root):
    return Workspace(root, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False, sync=True)


@unittest.skipUnless(backup.available(), "needs the cryptography package")
class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gh = FakeGitHub()
        self.env = {"KINTSUGI_BACKUP_REPO": "me/vault", "KINTSUGI_BACKUP_TOKEN": "ghp_secret_token_value",
                    "KINTSUGI_BACKUP_PASSPHRASE": PASS, "KINTSUGI_GITHUB_API": self.gh.url}
        self.saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)

    def tearDown(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.gh.close()
        self.tmp.cleanup()

    def seeded(self, name="a"):
        ws = make_ws(self.root / name)
        ws.create_agent("alice", persona="p")
        ws.create_room("team", ["alice", "you"])
        ws.post("team", "you", "remember the pineapple", human=True)
        (ws.files_dir("alice")).mkdir(parents=True, exist_ok=True)
        (ws.files_dir("alice") / "plan.txt").write_text("launch on friday")
        return ws

    def test_encrypt_round_trip_and_wrong_passphrase(self):
        blob = backup.encrypt(b"secret data", PASS)
        self.assertNotIn(b"secret data", blob)
        self.assertEqual(backup.decrypt(blob, PASS), b"secret data")
        with self.assertRaises(backup.BackupError):
            backup.decrypt(blob, "another passphrase here")
        with self.assertRaises(backup.BackupError):
            backup.decrypt(blob[:-3] + b"xyz", PASS)  # tampering is detected
        with self.assertRaises(backup.BackupError):
            backup.decrypt(b"not a backup at all, really", PASS)

    def test_backup_then_restore_onto_empty_disk(self):
        ws = self.seeded()
        result = ws.backups.run(force=True)
        self.assertTrue(result["ok"], result)
        blob = self.gh.files[backup.DEFAULT_PATH]
        self.assertNotIn(b"pineapple", blob)
        self.assertNotIn(b"launch on friday", blob)
        ws.close()
        fresh = self.root / "wiped"
        self.assertTrue(backup.restore_if_empty(fresh, say=lambda m: None))
        restored = make_ws(fresh)
        self.assertEqual([a["name"] for a in restored.list_agents()], ["alice"])
        self.assertTrue(any("pineapple" in m["text"] for m in restored.history("team", limit=50)))
        self.assertEqual((restored.files_dir("alice") / "plan.txt").read_text(), "launch on friday")
        restored.close()

    def test_restore_never_overwrites_existing_data(self):
        ws = self.seeded()
        ws.backups.run(force=True)
        ws.close()
        other = self.seeded("b")
        other.create_agent("carol", persona="x")
        other.close()
        self.assertFalse(backup.restore_if_empty(self.root / "b", say=lambda m: None))
        again = make_ws(self.root / "b")
        self.assertIn("carol", [a["name"] for a in again.list_agents()])
        again.close()

    def test_wrong_passphrase_on_restore_leaves_disk_empty_and_says_why(self):
        ws = self.seeded()
        ws.backups.run(force=True)
        ws.close()
        os.environ["KINTSUGI_BACKUP_PASSPHRASE"] = "a completely different phrase"
        said = []
        self.assertFalse(backup.restore_if_empty(self.root / "wiped", say=said.append))
        self.assertIn("passphrase", " ".join(said))
        self.assertFalse((self.root / "wiped" / "workspace.db").exists())

    def test_public_repository_is_refused_and_nothing_uploaded(self):
        self.gh.private = False
        ws = self.seeded()
        result = ws.backups.run(force=True)
        self.assertFalse(result["ok"])
        self.assertIn("PUBLIC", result["error"])
        self.assertEqual(self.gh.files, {})
        ws.close()

    def test_bad_token_gives_a_clear_error_and_never_leaks_it(self):
        self.gh.reject = True
        ws = self.seeded()
        result = ws.backups.run(force=True)
        self.assertFalse(result["ok"])
        status = json.dumps(ws.backups.status())
        log = json.dumps(ws.audit_log(50))
        for text in (status, log):
            self.assertNotIn("ghp_secret_token_value", text)
            self.assertNotIn(PASS, text)
        ws.close()

    def test_token_file_is_not_carried_in_backups(self):
        ws = self.seeded()
        (ws.root / "token").write_text("access-token-123")
        data = backup.snapshot(ws)
        import io, tarfile
        names = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz").getnames()
        self.assertNotIn("token", names)
        self.assertIn("workspace.db", names)
        ws.close()

    def test_unsafe_archives_are_rejected(self):
        import io, tarfile
        for name, kind in (("../evil.txt", "file"), ("/abs.txt", "file"), ("link", "sym")):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
                info = tarfile.TarInfo(name)
                if kind == "sym":
                    info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
                tar.addfile(info, io.BytesIO(b"x") if kind == "file" else None)
            with self.assertRaises(backup.BackupError, msg=name):
                backup.unpack(buffer.getvalue(), self.root / "target")
        self.assertFalse((self.root / "evil.txt").exists())

    def test_only_changed_workspaces_are_uploaded_again(self):
        ws = self.seeded()
        self.assertTrue(ws.backups.run()["ok"])
        puts = lambda: len([r for r in self.gh.requests if r[0] == "PUT"])
        self.assertEqual(puts(), 1)
        self.assertIn("nothing changed", ws.backups.run()["error"])
        self.assertEqual(puts(), 1)
        ws.post("team", "you", "something new", human=True)
        self.assertTrue(ws.backups.run()["ok"])
        self.assertEqual(puts(), 2)
        ws.close()

    def test_scheduler_hook_respects_the_interval(self):
        ws = self.seeded()
        os.environ["KINTSUGI_BACKUP_EVERY_MINUTES"] = "60"
        try:
            self.assertTrue(ws.backups.maybe_run(1000.0))
            ws.backups._thread.join(10)
            self.assertFalse(ws.backups.maybe_run(1000.0 + 120))  # too soon
            ws.post("team", "you", "more", human=True)
            ws.backups._last_check = 0
            self.assertTrue(ws.backups.maybe_run(ws.backups.status()["last"]["ts"] + 3700))
            ws.backups._thread.join(10)
        finally:
            os.environ.pop("KINTSUGI_BACKUP_EVERY_MINUTES")
        ws.close()

    def test_configuration_is_validated(self):
        os.environ["KINTSUGI_BACKUP_PASSPHRASE"] = "short"
        with self.assertRaises(backup.BackupError):
            backup.config()
        os.environ["KINTSUGI_BACKUP_PASSPHRASE"] = PASS
        os.environ["KINTSUGI_BACKUP_REPO"] = "not a repo"
        with self.assertRaises(backup.BackupError):
            backup.config()
        os.environ["KINTSUGI_BACKUP_REPO"] = "me/vault"
        os.environ["KINTSUGI_BACKUP_PATH"] = "../escape"
        try:
            with self.assertRaises(backup.BackupError):
                backup.config()
        finally:
            os.environ.pop("KINTSUGI_BACKUP_PATH")

    def test_status_when_not_configured(self):
        for k in self.env:
            os.environ.pop(k, None)
        ws = self.seeded()
        status = ws.backups.status()
        self.assertFalse(status["configured"])
        self.assertFalse(ws.backups.run()["ok"])
        ws.close()


@unittest.skipUnless(backup.available(), "needs the cryptography package")
class BackupApiTests(BackupTests):
    def setUp(self):
        super().setUp()
        self.ws = self.seeded()
        self.ws.sync = False
        self.server = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ws.close()
        super().tearDown()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": "secret-token"})
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, json.loads(raw), raw.decode()

    def test_status_run_and_no_secrets_anywhere(self):
        status, data, _ = self.call("GET", "/api/backup")
        self.assertEqual((status, data["configured"], data["repo"], data["last"]), (200, True, "me/vault", None))
        self.assertEqual(self.call("POST", "/api/backup/run", {})[0], 200)
        self.ws.backups._thread.join(20)
        data = self.call("GET", "/api/backup")[1]
        self.assertTrue(data["last"]["ok"], data)
        self.assertIn(backup.DEFAULT_PATH, self.gh.files)
        outputs = [self.call("GET", p)[2] for p in ("/api/backup", "/api/state", "/api/export", "/api/audit")]
        for text in outputs:
            self.assertNotIn("ghp_secret_token_value", text)
            self.assertNotIn(PASS, text)

    def test_endpoints_need_the_access_token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request("POST", "/api/backup/run", "{}", {})
        self.assertEqual(conn.getresponse().status, 401)

    # inherited tests need a clean slate, not the server; skip re-running them here
    for _name in [n for n in dir(BackupTests) if n.startswith("test_")]:
        locals()[_name] = None


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(backup.available(), "needs the cryptography package")
class RollbackAndClobberTests(BackupTests):
    def test_a_second_copy_cannot_overwrite_a_newer_backup(self):
        a = self.seeded("a")
        self.assertTrue(a.backups.run(force=True)["ok"])  # backup #1
        b = self.seeded("b")  # a different, fresh workspace pointed at the same repository (a forgotten second server)
        result = b.backups.run(force=True)
        self.assertFalse(result["ok"])
        self.assertIn("newer", result["error"])
        self.assertTrue(a.backups.run(force=True)["ok"])  # the owner of the backup can keep going (#2)
        os.environ["KINTSUGI_BACKUP_OVERWRITE"] = "1"
        try:
            self.assertTrue(b.backups.run(force=True)["ok"])  # on purpose
        finally:
            del os.environ["KINTSUGI_BACKUP_OVERWRITE"]

    def test_a_backup_that_cannot_be_read_is_not_overwritten(self):
        a = self.seeded("a")
        self.assertTrue(a.backups.run(force=True)["ok"])
        os.environ["KINTSUGI_BACKUP_PASSPHRASE"] = "a completely different passphrase"
        result = self.seeded("b").backups.run(force=True)
        self.assertFalse(result["ok"])
        self.assertIn("cannot be read", result["error"])

    def test_restore_continues_the_count_and_refuses_a_replayed_old_backup(self):
        a = self.seeded("a")
        a.backups.run(force=True)
        a.post("team", "you", "more", human=True)
        a.backups.run(force=True)  # #2 is what GitHub holds
        a.close()
        self.gh.commit_date = "2099-01-01T00:00:00Z"  # committed far later than the backup says it was made: a replay
        fresh = self.root / "fresh"
        self.assertFalse(backup.restore_if_empty(fresh, say=lambda *_: None))
        self.assertFalse((fresh / "workspace.db").exists())
        os.environ["KINTSUGI_BACKUP_ACCEPT_OLD"] = "1"
        try:
            self.assertTrue(backup.restore_if_empty(fresh, say=lambda *_: None))
        finally:
            del os.environ["KINTSUGI_BACKUP_ACCEPT_OLD"]
        ws = make_ws(fresh)
        self.assertEqual(ws.get_setting("backup_counter"), "2")  # a restored workspace carries on from #2, so it may write #3
        self.assertTrue(ws.backups.run(force=True)["ok"])
        self.assertFalse((fresh / "backup.meta.json").exists())  # the label is not unpacked into the workspace

    def test_a_normal_restore_is_not_refused_when_dates_agree(self):
        a = self.seeded("a")
        a.backups.run(force=True)
        a.close()
        import time as _t
        self.gh.commit_date = _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime())
        self.assertTrue(backup.restore_if_empty(self.root / "fresh", say=lambda *_: None))
