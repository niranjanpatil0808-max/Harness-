import base64
import http.client
import json
import tempfile
import threading
import time
import unittest

from kintsugi.model import Usage
from kintsugi.workspace import Workspace, templates, uploads
from kintsugi.workspace.core import WorkspaceError
from kintsugi.workspace.server import make_server

OWNER = "owner-token-0123456789-0123456789"


class TokenModel:
    """A scripted model that reports token usage like a real adapter."""

    name = "tok-model"

    def __init__(self, replies, gate=None):
        self.usage, self.replies, self.gate = Usage(), list(replies), gate

    def complete(self, messages):
        if self.gate is not None:
            self.gate.wait(10)
        self.usage.calls += 1
        self.usage.prompt_tokens += 100
        self.usage.completion_tokens += 20
        return self.replies.pop(0) if self.replies else "all done here"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.model = TokenModel([])
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: self.model, encrypt_keychain=False, sync=False)
        self.ws.create_agent("alice", persona="p")
        self.ws.create_room("team", ["alice", "you"])
        self.ws.create_room("secret", ["alice", "you"])
        self.api = make_server(self.ws, port=0, token=OWNER)
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.tokens = {"owner": OWNER}

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.ws.close()
        self.tmp.cleanup()

    def call(self, who, method, path, body=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": self.tokens.get(who, who) or ""})
        resp = conn.getresponse()
        data = resp.read()
        if raw:
            return resp.status, data, resp
        try:
            return resp.status, json.loads(data)
        except json.JSONDecodeError:
            return resp.status, data.decode()

    def join(self, name, role="member", rooms=None):
        _, invite = self.call("owner", "POST", "/api/team/invite", {"role": role, **({"rooms": rooms} if rooms is not None else {})})
        _, joined = self.call(None, "POST", "/api/join", {"code": invite["code"], "name": name})
        self.tokens[name] = joined["token"]


class TestStopAndActivity(Base):
    def test_a_working_agent_can_be_stopped_and_shows_what_it_is_doing(self):
        gate = threading.Event()
        self.model.gate = gate
        self.model.replies = ['```tool\n{"tool": "list_files", "args": {"path": "."}}\n```'] * 10
        self.ws.post("team", "you", "@alice keep going", human=True)
        for _ in range(100):
            if "alice" in self.ws.busy():
                break
            time.sleep(0.05)
        state = self.call("owner", "GET", "/api/state")[1]
        self.assertEqual(state["activity"].get("alice"), "thinking")
        self.assertEqual(self.call("owner", "POST", "/api/stop", {"agent": "alice"})[1], {"stopping": True})
        gate.set()
        self.assertTrue(self.ws.wait_idle(10))
        texts = [m["text"] for m in self.ws.history("team", limit=20)]
        self.assertIn("alice was stopped.", texts)
        self.assertLessEqual(self.model.usage.calls, 2)  # it did not carry on for ten steps
        self.assertEqual(self.call("owner", "GET", "/api/state")[1]["activity"], {})
        self.assertEqual(self.call("owner", "POST", "/api/stop", {"agent": "alice"})[1], {"stopping": False})  # nothing to stop

    def test_a_member_can_only_stop_agents_working_in_their_chats(self):
        self.join("sam")
        gate = threading.Event()
        self.model.gate = gate
        self.ws.post("secret", "you", "@alice work", human=True)
        for _ in range(100):
            if "alice" in self.ws.busy():
                break
            time.sleep(0.05)
        self.assertEqual(self.call("sam", "POST", "/api/stop", {"agent": "alice"})[0], 403)
        gate.set()
        self.ws.wait_idle(10)


class TestUsage(Base):
    def test_calls_and_tokens_are_counted_per_agent_and_model_with_optional_prices(self):
        self.ws.post("team", "you", "@alice hello", human=True)
        self.assertTrue(self.ws.wait_idle(10))
        report = self.call("owner", "GET", "/api/usage")[1]
        self.assertEqual(report["by_agent"][0]["name"], "alice")
        self.assertEqual((report["by_agent"][0]["calls"], report["by_agent"][0]["prompt_tokens"], report["by_agent"][0]["completion_tokens"]), (1, 100, 20))
        self.assertTrue(report["tokens_known"])
        self.assertFalse(report["by_model"][0]["priced"])
        self.assertEqual(self.call("owner", "POST", "/api/usage/price", {"model": "tok-model", "in": 1.0, "out": 2.0})[0], 200)
        report = self.call("owner", "GET", "/api/usage")[1]
        self.assertEqual(report["by_model"][0]["cost"], round((100 * 1.0 + 20 * 2.0) / 1e6, 4))
        self.assertEqual(self.call("owner", "POST", "/api/usage/price", {"model": "x", "in": -1, "out": 1})[0], 400)

    def test_members_cannot_see_usage_or_set_prices(self):
        self.join("sam")
        self.assertEqual(self.call("sam", "GET", "/api/usage")[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/usage/price", {"model": "x", "in": 1, "out": 1})[0], 403)


class TestFind(Base):
    def test_search_only_reaches_rooms_you_are_in_and_escapes_wildcards(self):
        self.join("sam", rooms=["team"])
        self.ws.post("team", "you", "the launch plan is 100% ready", human=True)
        self.ws.post("secret", "you", "the launch codes are hidden", human=True)
        self.ws.post("team", "you", "plain words only", human=True)
        owner = self.call("owner", "GET", "/api/find?q=launch")[1]
        self.assertEqual(sorted(r["room"] for r in owner), ["secret", "team"])
        member = self.call("sam", "GET", "/api/find?q=launch")[1]
        self.assertEqual([r["room"] for r in member], ["team"])
        self.assertIn("100%", self.call("owner", "GET", "/api/find?q=100%25")[1][0]["snippet"])
        self.assertEqual(self.call("owner", "GET", "/api/find?q=%25")[1], [])  # too short; a bare % is not a wildcard
        self.assertEqual(len(self.call("owner", "GET", "/api/find?q=plain_words")[1]), 0)  # _ is literal
        self.assertEqual(self.call("owner", "GET", "/api/find?q=a")[1], [])


class TestTemplates(Base):
    def test_a_template_creates_agents_and_a_room_once(self):
        self.assertIn("founder", [t["id"] for t in self.call("owner", "GET", "/api/templates")[1]])
        made = self.call("owner", "POST", "/api/templates/apply", {"id": "founder"})[1]
        self.assertEqual(sorted(made["agents"]), ["chief", "scout", "scribe"])
        self.assertEqual(made["room"], "founder-team")  # 'team' already exists here
        self.assertIn("you", self.ws.members("founder-team"))
        again = self.call("owner", "POST", "/api/templates/apply", {"id": "founder"})[1]
        self.assertEqual((again["agents"], again["room"]), ([], None))
        self.assertEqual(self.call("owner", "POST", "/api/templates/apply", {"id": "nope"})[0], 400)
        for t in templates.TEMPLATES.values():
            for _, persona in t["agents"]:
                self.assertIn("never invent", persona)

    def test_only_admins_can_apply_templates(self):
        self.join("sam")
        self.assertEqual(self.call("sam", "POST", "/api/templates/apply", {"id": "solo"})[0], 403)


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class TestUploads(Base):
    def test_a_text_file_is_saved_safely_and_never_overwrites(self):
        first = self.call("owner", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": "notes.md", "data": b64("# notes\nhello")})[1]["path"]
        second = self.call("owner", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": "notes.md", "data": b64("other")})[1]["path"]
        self.assertEqual((first, second), ("uploads/notes.md", "uploads/notes (2).md"))
        from kintsugi.workspace import uploads

        self.assertEqual(uploads.resolve(self.ws, "alice", "team", first).read_text(), "# notes\nhello")
        self.assertFalse((self.ws.files_dir("alice") / "uploads").exists())  # kept outside the agent's own folder

    def test_bad_files_are_refused_with_a_reason(self):
        bad = [("a.pdf", b64("x")), ("../evil.txt", b64("x")), (".hidden.txt", b64("x")), ("a/b.txt", b64("x")), ("run.exe", b64("x")), ("a.txt", b64("")),
               ("a.txt", "!!notbase64!!"), ("a.txt", base64.b64encode(b"ab\x00cd").decode()), ("a.txt", base64.b64encode(b"\xff\xfe\xfa").decode()),
               ("a.txt", b64("x" * 1_600_000)), ("x" * 100 + ".txt", b64("x"))]
        for name, data in bad:
            status, body = self.call("owner", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": name, "data": data})
            self.assertEqual(status, 400, (name, body))
        self.assertEqual(list((self.ws.files_dir("alice") / "uploads").iterdir()) if (self.ws.files_dir("alice") / "uploads").exists() else [], [])

    def test_members_can_only_give_files_to_agents_they_share_a_chat_with(self):
        self.ws.create_agent("bob")
        self.ws.create_room("bobs", ["bob", "you"])
        self.join("sam", rooms=["team"])
        self.assertEqual(self.call("sam", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": "a.txt", "data": b64("hi")})[0], 200)
        self.assertEqual(self.call("sam", "POST", "/api/upload", {"agent": "bob", "room": "team", "name": "a.txt", "data": b64("hi")})[0], 403)

    def test_download_is_for_admins_and_sent_as_an_inert_attachment(self):
        (self.ws.files_dir("alice")).mkdir(parents=True, exist_ok=True)
        (self.ws.files_dir("alice") / "page<1>.html").write_text("<script>alert(1)</script>")
        status, data, resp = self.call("owner", "GET", "/api/download?agent=alice&path=" + "page%3C1%3E.html", raw=True)
        self.assertEqual(status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/octet-stream")
        self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
        self.assertIn("attachment", resp.getheader("Content-Disposition"))
        self.assertNotIn("<", resp.getheader("Content-Disposition"))
        self.join("sam")
        self.assertEqual(self.call("sam", "GET", "/api/download?agent=alice&path=page.html")[0], 403)
        for bad in ("../../token", "/etc/passwd", "uploads/../../../workspace.db", "uploads/../../../workspace.db&room=team"):
            self.assertIn(self.call("owner", "GET", f"/api/download?agent=alice&path={bad}")[0], (400, 403), bad)

    def test_the_agent_can_read_what_was_uploaded(self):
        from kintsugi.workspace.tools import Ctx, execute

        path = self.call("owner", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": "data.csv", "data": b64("a,b\n1,2")})[1]["path"]
        out = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "read_file", {"path": path})
        self.assertEqual((out.status, "1,2" in out.output), ("ok", True))

    def test_a_huge_body_is_refused_before_it_is_read(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=10)
        conn.request("POST", "/api/upload", "x" * 10, {"X-Token": OWNER, "Content-Length": "99999999"})
        self.assertEqual(conn.getresponse().status, 400)


class TestResetSignIn(Base):
    def test_admin_resets_a_member_owner_resets_anyone_and_the_old_token_dies(self):
        self.join("sam")
        self.join("ada", "admin")
        old = self.tokens["sam"]
        new = self.call("ada", "POST", "/api/team/reset", {"name": "sam"})[1]["token"]
        self.assertEqual(self.call(old, "GET", "/api/me")[0], 401)
        self.assertEqual(self.call(new, "GET", "/api/me")[1]["name"], "sam")
        self.assertEqual(self.call("ada", "POST", "/api/team/reset", {"name": "ada"})[0], 400)  # not for admins
        self.assertEqual(self.call("owner", "POST", "/api/team/reset", {"name": "ada"})[0], 200)
        self.assertEqual(self.call(new, "POST", "/api/team/reset", {"name": "sam"})[0], 403)


class TestProviderTesting(Base):
    def test_a_wrong_address_fails_fast_with_a_plain_message(self):
        self.ws.set_provider("bad", "openai", "http://127.0.0.1:1/v1", "m", key="sk-test-key-12345")
        started = time.time()
        result = self.ws.test_provider("bad")
        self.assertFalse(result["ok"])
        self.assertLess(time.time() - started, 8)
        self.assertNotIn("sk-test-key-12345", json.dumps(result))

    def test_non_ai_answers_and_internal_addresses(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class Html(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "6")
                self.end_headers()
                self.wfile.write(b"<html>")

            do_POST = do_GET

        site = ThreadingHTTPServer(("127.0.0.1", 0), Html)
        threading.Thread(target=site.serve_forever, daemon=True).start()
        try:
            self.ws.set_provider("html", "openai", f"http://127.0.0.1:{site.server_port}/v1", "m", key="sk-test-key-12345")
            result = self.ws.test_provider("html")
            self.assertFalse(result["ok"])
            self.assertIn("did not answer like an AI service", result["error"])
        finally:
            site.shutdown()
        for bad in ("https://169.254.169.254/v1", "https://10.0.0.5/v1", "https://192.168.1.1/v1"):
            with self.assertRaises(WorkspaceError):
                self.ws.set_provider("meta", "openai", bad, "m", key="sk-test-key-12345")


if __name__ == "__main__":
    unittest.main()
