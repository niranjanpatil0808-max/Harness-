import http.client
import json
import tempfile
import threading
import unittest

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.server import make_server


class TestServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["hello from agent"]), sync=False,
                            encrypt_keychain=False)
        self.ws.create_agent("alice")
        self.ws.create_room("general", ["alice", "you"])
        self.server = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ws.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token="secret-token"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"X-Token": token} if token else {}
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data, resp

    def test_page_is_public_but_api_needs_the_token(self):
        self.assertEqual(self.call("GET", "/", token=None)[0], 200)
        self.assertEqual(self.call("GET", "/api/state", token=None)[0], 401)
        self.assertEqual(self.call("GET", "/api/state", token="wrong")[0], 401)
        self.assertEqual(self.call("POST", "/api/say", {"room": "general", "text": "x"}, token="wrong")[0], 401)

    def test_state_and_say(self):
        status, data, _ = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["agents"][0]["name"], "alice")
        status, _, _ = self.call("POST", "/api/say", {"room": "general", "text": "@alice hi"})
        self.assertEqual(status, 200)
        self.assertTrue(self.ws.wait_idle(10))  # let the agent finish
        _, data, _ = self.call("GET", "/api/messages?room=general")
        self.assertEqual([m["sender"] for m in json.loads(data)], ["you", "alice"])

    def test_people_cannot_pose_as_agents(self):
        status, data, _ = self.call("POST", "/api/say", {"room": "general", "text": "hi", "as": "alice"})
        self.assertEqual(status, 400)
        self.assertIn("not available", json.loads(data)["error"])

    def test_bad_requests_are_errors_not_crashes(self):
        self.assertEqual(self.call("POST", "/api/say", {"room": "nope", "text": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/say", {"text": "x"})[0], 400)
        self.assertEqual(self.call("GET", "/api/messages?room=nope")[0], 400)
        self.assertEqual(self.call("GET", "/api/unknown")[0], 400)
        self.assertEqual(self.call("POST", "/api/approve", {"id": 999, "approve": True})[0], 400)

    def test_published_apps_are_served_with_a_sandbox_policy(self):
        app = self.ws.www_dir("alice") / "todo"
        app.mkdir()
        (app / "index.html").write_text("<h1>todo</h1>")
        status, data, resp = self.call("GET", "/apps/alice/todo/")
        self.assertEqual((status, data), (200, b"<h1>todo</h1>"))
        self.assertIn("sandbox", resp.getheader("Content-Security-Policy"))
        self.assertEqual(self.call("GET", "/apps/alice/todo/", token=None)[0], 401)

    def test_app_paths_cannot_escape(self):
        (self.ws.agent_dir("alice") / "lessons.json").write_text("[]")
        (self.ws.files_dir("alice") / "private.txt").write_text("mine")
        for path in ("/apps/alice/../files/private.txt", "/apps/alice/%2e%2e/files/private.txt",
                     "/apps/alice/x/..%2f..%2ffiles%2fprivate.txt", "/apps/nobody/x/index.html"):
            status, data, _ = self.call("GET", path)
            self.assertNotEqual(status, 200, path)
            self.assertNotIn(b"mine", data)

    def test_approval_flow_over_http(self):
        self.ws.request_approval("alice", "general", "run_python", {"code": "print(6*7)"})
        _, data, _ = self.call("GET", "/api/state")
        approval = json.loads(data)["approvals"][0]
        status, data, _ = self.call("POST", "/api/approve", {"id": approval["id"], "approve": True})
        self.assertEqual((status, json.loads(data)["output"]), (200, "42"))

    def test_state_reports_busy_agents_apps_and_secret_names_but_never_values(self):
        self.ws.keychain.set("alice", "DEMO_KEY", "sk-very-secret-value")
        app = self.ws.www_dir("alice") / "todo"
        app.mkdir()
        (app / "index.html").write_text("x")
        _, data, _ = self.call("GET", "/api/state")
        state = json.loads(data)
        alice = state["agents"][0]
        self.assertEqual((alice["secrets"], alice["apps"], state["busy"]), (["DEMO_KEY"], ["todo"], []))
        self.assertNotIn("sk-very-secret-value", data.decode())

    def test_file_endpoint_reads_inside_the_folder_only(self):
        (self.ws.files_dir("alice") / "a.txt").write_text("hello")
        (self.ws.agent_dir("alice") / "lessons.json").write_text("{}")
        status, data, _ = self.call("GET", "/api/file?agent=alice&path=a.txt")
        self.assertEqual((status, json.loads(data)["text"]), (200, "hello"))
        for bad in ("../lessons.json", "/etc/passwd", "nope.txt"):
            self.assertEqual(self.call("GET", f"/api/file?agent=alice&path={bad}")[0], 400, bad)

    def test_garbage_input_gets_an_error_not_a_dropped_connection(self):
        self.assertEqual(self.call("GET", "/api/messages?room=general&after=abc")[0], 400)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/say", "{not json", {"X-Token": "secret-token", "Content-Length": "9"})
        self.assertEqual(conn.getresponse().status, 400)
        status, _, _ = self.call("POST", "/api/approve", {"id": "x", "approve": True})
        self.assertEqual(status, 400)

    def test_unexpected_bugs_become_a_500_and_an_audit_entry(self):
        from unittest import mock

        with mock.patch.object(self.ws, "list_agents", side_effect=RuntimeError("boom")):
            status, data, _ = self.call("GET", "/api/state")
        self.assertEqual(status, 500)
        self.assertNotIn("boom", data.decode())
        self.assertTrue(any(r["event"] == "server-error" for r in self.ws.audit_log()))

    def test_the_page_and_its_assets_are_served_and_cannot_escape(self):
        for path, kind in (("/static/app.js", "javascript"), ("/static/app.css", "css"), ("/static/logo.svg", "svg"),
                           ("/static/vendor/marked.min.js", "javascript"), ("/static/vendor/purify.min.js", "javascript")):
            status, data, resp = self.call("GET", path, token=None)
            self.assertEqual(status, 200, path)
            self.assertIn(kind, resp.getheader("Content-Type"))
            self.assertTrue(data)
        for bad in ("/static/../server.py", "/static/%2e%2e/core.py", "/static/index.html", "/static/nothing.js", "/static/vendor"):
            self.assertEqual(self.call("GET", bad, token=None)[0], 404, bad)
        page = self.call("GET", "/", token=None)[1].decode()
        for asset in ("/static/app.js", "/static/app.css", "/static/vendor/marked.min.js", "/static/vendor/purify.min.js"):
            self.assertIn(asset, page)

    def test_vendored_libraries_ship_with_their_licenses(self):
        from pathlib import Path

        vendor = Path(__file__).resolve().parent.parent / "src" / "kintsugi" / "workspace" / "web" / "vendor"
        for name in ("marked.LICENSE.md", "purify.LICENSE"):
            self.assertTrue((vendor / name).is_file(), name)

    def test_persona_can_be_changed_over_http(self):
        self.assertEqual(self.call("POST", "/api/persona", {"agent": "alice", "persona": "You are terse."})[0], 200)
        self.assertEqual(self.ws.get_agent("alice")["persona"], "You are terse.")
        self.assertEqual(self.call("POST", "/api/persona", {"agent": "nobody", "persona": "x"})[0], 400)

    def make_app(self):
        app = self.ws.www_dir("alice") / "todo"
        app.mkdir()
        (app / "index.html").write_text("<h1>todo</h1>")

    def test_app_links_are_signed_expire_and_work_for_one_app_only(self):
        self.make_app()
        other = self.ws.www_dir("alice") / "other"
        other.mkdir()
        (other / "index.html").write_text("other")
        status, data, _ = self.call("GET", "/api/applink?agent=alice&app=todo")
        link = json.loads(data)["url"]
        self.assertNotIn("secret-token", link)  # the access token never goes into a URL
        self.assertEqual(self.call("GET", link, token=None)[0], 200)
        self.assertEqual(self.call("GET", link.replace("/todo/", "/other/"), token=None)[0], 401)  # not for another app
        self.assertEqual(self.call("GET", link[:-3] + "000", token=None)[0], 401)  # tampered signature
        expired = "/apps/alice/todo/?exp=1&sig=" + link.split("sig=")[1]
        self.assertEqual(self.call("GET", expired, token=None)[0], 401)
        self.assertEqual(self.call("GET", "/apps/alice/todo/?token=secret-token", token=None)[0], 401)  # no token in URLs
        self.assertEqual(self.call("GET", "/api/applink?agent=alice&app=nope")[0], 400)

    def test_a_signed_link_cannot_reach_a_sibling_app_through_dot_dot(self):
        self.make_app()
        other = self.ws.www_dir("alice") / "other"
        other.mkdir()
        (other / "index.html").write_text("SIBLING")
        link = json.loads(self.call("GET", "/api/applink?agent=alice&app=todo")[1])["url"]
        sneaky = link.replace("/todo/?", "/todo/../other/index.html?")
        status, data, _ = self.call("GET", sneaky, token=None)
        self.assertNotEqual(status, 200)
        self.assertNotIn(b"SIBLING", data)

    def test_a_negative_content_length_is_rejected_instead_of_hanging(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", "/api/say")
        conn.putheader("X-Token", "secret-token")
        conn.putheader("Content-Length", "-5")
        conn.endheaders()
        self.assertEqual(conn.getresponse().status, 400)

    def test_idle_connections_are_dropped(self):
        from kintsugi.workspace import server as server_module

        handler = self.server.RequestHandlerClass
        self.assertTrue(0 < handler.timeout <= 60, handler.timeout)

    def test_security_headers_and_health_check(self):
        status, data, resp = self.call("GET", "/", token=None)
        self.assertIn("script-src 'self'", resp.getheader("Content-Security-Policy"))
        self.assertIn("frame-ancestors 'none'", resp.getheader("Content-Security-Policy"))
        self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer")
        status, data, _ = self.call("GET", "/healthz", token=None)
        self.assertEqual((status, json.loads(data)), (200, {"ok": True}))

    def test_many_wrong_tokens_get_a_client_turned_away_even_with_the_right_one(self):
        for _ in range(10):
            self.assertEqual(self.call("GET", "/api/state", token="guess")[0], 401)
        self.assertEqual(self.call("GET", "/api/state")[0], 401)  # throttled: even the real token is refused for a while

    def test_a_weak_token_is_refused_when_listening_on_a_network(self):
        with self.assertRaises(SystemExit) as caught:
            make_server(self.ws, host="0.0.0.0", port=0, token="short")
        self.assertIn("KINTSUGI_TOKEN", str(caught.exception))
        strong = make_server(self.ws, host="0.0.0.0", port=0, token="x" * 32)
        strong.server_close()

    def test_secrets_can_be_stored_but_never_come_back(self):
        status, data, _ = self.call("POST", "/api/secret", {"agent": "alice", "name": "API_TOKEN", "value": "sk-very-secret-value"})
        self.assertEqual(status, 200)
        self.assertNotIn("sk-very-secret", data.decode())
        everything = self.call("GET", "/api/state")[1].decode() + self.call("GET", "/api/export")[1].decode() + \
            self.call("GET", "/api/audit")[1].decode()
        self.assertNotIn("sk-very-secret-value", everything)
        self.assertIn("API_TOKEN", self.call("GET", "/api/state")[1].decode())
        self.assertEqual(self.call("POST", "/api/secret", {"agent": "alice", "name": "bad name", "value": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/secret/delete", {"agent": "alice", "name": "API_TOKEN"})[0], 200)
        self.assertEqual(self.ws.keychain.names("alice"), [])

    def test_state_tells_the_user_where_data_goes_and_how_code_is_isolated(self):
        state = json.loads(self.call("GET", "/api/state")[1])
        self.assertIn("backend", state["sandbox"])
        self.assertTrue(state["provider"])
        self.assertEqual(set(state["usage"]), {"calls", "limit"})

    def test_delete_and_purge_endpoints(self):
        self.ws.post_system("general", "old")
        self.assertEqual(self.call("POST", "/api/purge", {"days": 0})[0], 200)
        self.assertEqual(self.call("POST", "/api/room/delete", {"name": "general"})[0], 200)
        self.assertEqual(self.call("POST", "/api/agent/delete", {"name": "alice"})[0], 200)
        self.assertEqual(self.call("POST", "/api/agent/delete", {"name": "alice"})[0], 400)
        self.assertEqual(json.loads(self.call("GET", "/api/state")[1])["agents"], [])

    def test_token_can_come_from_the_environment(self):
        from unittest import mock

        from kintsugi.workspace.server import load_token

        with mock.patch.dict("os.environ", {"KINTSUGI_TOKEN": "chosen-by-me"}):
            self.assertEqual(load_token(self.ws), "chosen-by-me")


if __name__ == "__main__":
    unittest.main()
