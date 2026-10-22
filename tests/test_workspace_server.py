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
        self.ws._pool.shutdown(wait=True)  # let the agent finish
        self.ws._pool = None
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


if __name__ == "__main__":
    unittest.main()
