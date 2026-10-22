"""One end-to-end path through the real server: a person adds their own key in the app, chats, and the model is called with it."""

import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from kintsugi.workspace import Workspace
from kintsugi.workspace.server import make_server

KEY = "sk-e2e-user-key-9876"


class FakeOpenAI(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenAI.seen.append({"auth": self.headers.get("Authorization"), "model": body["model"], "system": body["messages"][0]["content"]})
        reply = {"choices": [{"message": {"content": "Hello from the model you configured."}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        data = json.dumps({"data": [{"id": "fake-model-1"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TestFromNothingToChatting(unittest.TestCase):
    def setUp(self):
        FakeOpenAI.seen = []
        self.model_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAI)
        threading.Thread(target=self.model_server.serve_forever, daemon=True).start()
        patcher = mock.patch.dict(os.environ, {"KINTSUGI_API_KEY": "", "GROQ_API_KEY": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, encrypt_keychain=False, sync=False)  # the real model path, as the server runs it
        self.ws.create_agent("alice", persona="You help.")
        self.ws.create_room("team", ["alice", "you"])
        self.api = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=self.api.serve_forever, daemon=True).start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.model_server.shutdown()
        self.model_server.server_close()
        self.ws.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": "secret-token"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())

    def texts(self):
        return " | ".join(m["text"] for m in self.call("GET", "/api/messages?room=team&after=0")[1])

    def test_no_key_then_add_key_then_chat(self):
        self.assertFalse(self.call("GET", "/api/state")[1]["model_ready"])
        self.call("POST", "/api/say", {"room": "team", "text": "@alice hi"})
        self.assertTrue(self.ws.wait_idle(10))
        self.assertIn("Settings > Models", self.texts())  # a clear next step, not a stack trace
        # the person adds their own key (as the Models tab does)
        url = f"http://127.0.0.1:{self.model_server.server_port}/v1"
        self.assertEqual(self.call("POST", "/api/providers/save", {"id": "mine", "kind": "openai", "base_url": url, "model": "fake-model-1", "key": KEY})[0], 200)
        self.assertTrue(self.call("POST", "/api/providers/test", {"id": "mine"})[1]["ok"])
        self.assertTrue(self.call("GET", "/api/state")[1]["model_ready"])
        FakeOpenAI.seen.clear()
        self.call("POST", "/api/say", {"room": "team", "text": "@alice hello again"})
        self.assertTrue(self.ws.wait_idle(10))
        self.assertIn("Hello from the model you configured.", self.texts())
        self.assertEqual((FakeOpenAI.seen[-1]["auth"], FakeOpenAI.seen[-1]["model"]), (f"Bearer {KEY}", "fake-model-1"))
        # nothing the app can show contains the key
        everything = json.dumps([self.call("GET", p)[1] for p in ("/api/state", "/api/providers", "/api/export", "/api/audit")]) + self.texts()
        self.assertNotIn(KEY, everything)
        self.assertNotIn(KEY, FakeOpenAI.seen[-1]["system"])  # and the model is never told it


if __name__ == "__main__":
    unittest.main()
