import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kintsugi.workspace import providers
from kintsugi.workspace.core import Workspace, WorkspaceError
from kintsugi.workspace.server import make_server

KEY = "sk-user-very-secret-key"


class Fake(BaseHTTPRequestHandler):
    """One fake server that speaks the OpenAI, Anthropic and Gemini wire formats and records what it was sent."""

    seen: list = []
    fail: int = 0

    def log_message(self, *a):
        pass

    def _reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        Fake.seen.append({"method": "GET", "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}})
        if self.path.startswith("/v1/models"):
            return self._reply(200, {"data": [{"id": "claude-b"}, {"id": "claude-a"}]})
        if self.path.startswith("/v1beta/models"):
            return self._reply(200, {"models": [{"name": "models/gem-2", "supportedGenerationMethods": ["generateContent"]},
                                                {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]})
        if self.path.endswith("/models"):
            return self._reply(200, {"data": [{"id": "gpt-x"}]})
        self._reply(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append({"method": "POST", "path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if Fake.fail:
            return self._reply(401, {"error": "bad key"})
        if self.path.endswith("/chat/completions"):
            return self._reply(200, {"choices": [{"message": {"content": "OK from openai"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
        if self.path == "/v1/messages":
            return self._reply(200, {"content": [{"type": "text", "text": "OK from claude"}], "usage": {"input_tokens": 5, "output_tokens": 1}})
        if ":generateContent" in self.path:
            return self._reply(200, {"candidates": [{"content": {"parts": [{"text": "hidden", "thought": True}, {"text": "OK from gemini"}]}}],
                                     "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2}})
        self._reply(404, {})


class WithFake(unittest.TestCase):
    def setUp(self):
        Fake.seen, Fake.fail = [], 0
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"  # http is allowed for localhost only
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, encrypt_keychain=False, sync=True)  # the real model path: no scripted factory

    def tearDown(self):
        self.ws.close()
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()


class TestAdapters(WithFake):
    def test_openai_compatible(self):
        m = providers.build({"kind": "openai", "base_url": self.url, "model": "gpt-x"}, KEY)
        self.assertEqual(m.complete([{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]), "OK from openai")
        self.assertEqual(Fake.seen[0]["headers"]["authorization"], f"Bearer {KEY}")
        self.assertEqual(m.list_models(), ["gpt-x"])

    def test_anthropic_format_system_and_alternating_roles(self):
        m = providers.build({"kind": "anthropic", "base_url": self.url, "model": "claude-a"}, KEY)
        out = m.complete([{"role": "system", "content": "be brief"}, {"role": "user", "content": "one"}, {"role": "user", "content": "two"},
                          {"role": "assistant", "content": "ok"}, {"role": "user", "content": "three"}])
        self.assertEqual(out, "OK from claude")
        sent = Fake.seen[0]
        self.assertEqual(sent["headers"]["x-api-key"], KEY)
        self.assertIn("anthropic-version", sent["headers"])
        self.assertEqual(sent["body"]["system"], "be brief")
        self.assertEqual([t["role"] for t in sent["body"]["messages"]], ["user", "assistant", "user"])
        self.assertEqual(sent["body"]["messages"][0]["content"], "one\n\ntwo")
        self.assertEqual((m.usage.prompt_tokens, m.usage.completion_tokens), (5, 1))
        self.assertEqual(m.list_models(), ["claude-a", "claude-b"])

    def test_gemini_format_key_in_header_not_address(self):
        m = providers.build({"kind": "gemini", "base_url": self.url, "model": "gem-2"}, KEY)
        out = m.complete([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "again"}])
        self.assertEqual(out, "OK from gemini")  # thinking parts are dropped
        sent = Fake.seen[0]
        self.assertNotIn(KEY, sent["path"])
        self.assertEqual(sent["headers"]["x-goog-api-key"], KEY)
        self.assertEqual(sent["body"]["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual([c["role"] for c in sent["body"]["contents"]], ["user", "model", "user"])
        self.assertEqual(m.list_models(), ["gem-2"])  # only models that can generate

    def test_bad_key_is_a_setup_error_not_a_retry_storm(self):
        Fake.fail = 1
        m = providers.build({"kind": "anthropic", "base_url": self.url, "model": "x"}, KEY)
        with self.assertRaises(RuntimeError):
            m.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(len([s for s in Fake.seen if s["method"] == "POST"]), 1)


class TestWorkspaceProviders(WithFake):
    def save(self, pid="claude", kind="anthropic", model="claude-a", **kw):
        return self.ws.set_provider(pid, kind, self.url, model, key=kw.pop("key", KEY), **kw)

    def test_key_is_write_only_everywhere(self):
        self.save()
        listing = json.dumps(self.ws.providers())
        self.assertNotIn(KEY, listing)
        self.assertTrue(json.loads(listing)["profiles"][0]["has_key"])
        self.assertNotIn(KEY, json.dumps(self.ws.audit_log(100)))
        self.assertNotIn(KEY, json.dumps([self.ws.get_agent(a["name"]) for a in self.ws.list_agents()]))
        self.assertNotIn(KEY, self.ws.db.one("SELECT value FROM settings WHERE key = 'providers'")["value"])

    def test_first_provider_becomes_default_and_agents_use_it(self):
        self.save()
        self.ws.create_agent("alice", persona="p")
        self.assertEqual(self.ws.model_for("alice").complete([{"role": "user", "content": "hi"}]), "OK from claude")
        self.assertEqual(self.ws.model_for("alice").name, "claude-a")

    def test_per_agent_provider_and_model(self):
        self.save()
        self.save("gem", "gemini", "gem-2")
        self.ws.create_agent("alice", persona="p")
        self.ws.create_agent("bob", persona="p")
        self.ws.set_model("bob", "gem-2", "gem")
        self.assertEqual(self.ws.model_for("alice").complete([{"role": "user", "content": "x"}]), "OK from claude")
        self.assertEqual(self.ws.model_for("bob").complete([{"role": "user", "content": "x"}]), "OK from gemini")
        with self.assertRaises(WorkspaceError):
            self.ws.set_model("bob", "m", "nope")

    def test_removing_a_provider_deletes_its_key_and_frees_agents(self):
        self.save()
        self.save("gem", "gemini", "gem-2")
        self.ws.create_agent("bob", persona="p")
        self.ws.set_model("bob", "gem-2", "gem")
        self.ws.remove_provider("gem")
        self.assertIsNone(self.ws.get_agent("bob")["provider"])
        self.assertNotIn("PROVIDER_GEM_KEY", self.ws.keychain.names(self.ws.SEARCH_AGENT))

    def test_validation(self):
        for bad in ("http://evil.example.com/v1", "ftp://x.com", "https://user:pw@x.com", "https://x.com/v1?key=1", "", "https://a b.com"):
            with self.assertRaises(WorkspaceError, msg=bad):
                self.ws.set_provider("p1", "openai", bad, "m", key=KEY)
        with self.assertRaises(WorkspaceError):
            self.ws.set_provider("Bad Name", "openai", self.url, "m", key=KEY)
        with self.assertRaises(WorkspaceError):
            self.ws.set_provider("p1", "openai", self.url, "m")  # no key
        with self.assertRaises(WorkspaceError):
            self.ws.set_provider("p1", "openai", self.url, "bad model!", key=KEY)
        self.ws.set_provider("local", "openai", self.url, "m", keyless=True)  # a local model needs no key

    def test_test_button_lists_models_and_reports_errors_without_the_key(self):
        self.save(model="")
        r = self.ws.test_provider("claude")
        self.assertTrue(r["ok"] and r["models"] == ["claude-a", "claude-b"], r)
        self.save(model="claude-a")
        self.assertEqual(self.ws.test_provider("claude")["reply"], "OK from claude")
        Fake.fail = 1
        r = self.ws.test_provider("claude")
        self.assertFalse(r["ok"])
        self.assertNotIn(KEY, json.dumps(r))

    def test_no_setup_gives_a_friendly_message_in_the_room(self):
        import os
        saved = {k: os.environ.pop(k, None) for k in ("KINTSUGI_API_KEY", "GROQ_API_KEY")}
        try:
            self.ws.create_agent("alice", persona="p")
            self.ws.create_room("team", ["alice", "you"])
            self.ws.post("team", "you", "@alice hi", human=True)
            texts = " ".join(m["text"] for m in self.ws.history("team", limit=20))
            self.assertIn("Settings > Models", texts)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class TestProviderApi(WithFake):
    def setUp(self):
        super().setUp()
        self.ws.sync = False
        self.api = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=self.api.serve_forever, daemon=True).start()

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        super().tearDown()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=20)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": "secret-token"})
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, json.loads(raw), raw.decode()

    def test_save_test_default_remove_and_no_key_in_any_output(self):
        status, data, raw = self.call("POST", "/api/providers/save", {"id": "claude", "kind": "anthropic", "base_url": self.url, "model": "claude-a", "key": KEY})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("POST", "/api/providers/test", {"id": "claude"})[1]["reply"], "OK from claude")
        outputs = [raw] + [self.call("GET", p)[2] for p in ("/api/providers", "/api/state", "/api/export", "/api/audit")]
        self.assertFalse(any(KEY in o for o in outputs))
        self.assertEqual(self.call("POST", "/api/providers/save", {"id": "x", "kind": "openai", "base_url": "http://evil.example.com", "model": "m", "key": KEY})[0], 400)
        self.assertEqual(self.call("POST", "/api/providers/default", {"id": "claude"})[0], 200)
        self.assertEqual(self.call("POST", "/api/providers/remove", {"id": "claude"})[1]["profiles"], [])

    def test_needs_the_access_token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=10)
        conn.request("POST", "/api/providers/save", "{}", {})
        self.assertEqual(conn.getresponse().status, 401)
        self.assertEqual(self.call("GET", "/api/providers")[1]["presets"]["anthropic"]["kind"], "anthropic")
        meta = self.call("GET", "/api/providers")[1]["presets"]["meta"]  # Meta's Llama API speaks the OpenAI style at /compat/v1
        self.assertEqual((meta["kind"], meta["base_url"]), ("openai", "https://api.llama.com/compat/v1"))
        from kintsugi.workspace import providers
        self.assertEqual(providers.clean_base_url(meta["base_url"]), "https://api.llama.com/compat/v1")


if __name__ == "__main__":
    unittest.main()
