import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from kintsugi.model import OpenAIAdapter
from kintsugi.workspace import Workspace, providers
from tests.test_workspace_team import Base


class FakeAI:
    """One server that speaks OpenAI-style, Anthropic-style and Gemini-style, streaming or not, in different modes."""

    def __init__(self, mode="sse", pause=None):
        self.mode, self.pause, self.requests = mode, pause, []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                streaming = bool(body.get("stream")) or "streamGenerateContent" in self.path
                outer.requests.append((self.path, streaming))
                if outer.mode == "reject" and streaming:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error":"stream_options not supported"}')
                    return
                words = ["Hello", " from", " the", " stream", "."]
                if "/chat/completions" in self.path:
                    if streaming and outer.mode == "sse":
                        self._sse([{"choices": [{"delta": {"content": w}}]} for w in words] + [{"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 5}}], done=True)
                    else:
                        self._json({"choices": [{"message": {"content": "".join(words)}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
                elif "/v1/messages" in self.path:
                    if streaming and outer.mode == "sse":
                        events = [{"type": "message_start", "message": {"usage": {"input_tokens": 12}}}] + \
                                 [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": w}} for w in words] + [{"type": "message_delta", "usage": {"output_tokens": 6}}]
                        self._sse(events)
                    else:
                        self._json({"content": [{"type": "text", "text": "".join(words)}], "usage": {"input_tokens": 7, "output_tokens": 3}})
                else:
                    if streaming and outer.mode == "sse":
                        self._sse([{"candidates": [{"content": {"parts": [{"text": w}]}}]} for w in words[:-1]]
                                  + [{"candidates": [{"content": {"parts": [{"text": words[-1]}]}}], "usageMetadata": {"promptTokenCount": 13, "candidatesTokenCount": 7}}])
                    else:
                        self._json({"candidates": [{"content": {"parts": [{"text": "".join(words)}]}}], "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3}})

            def _json(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _sse(self, events, done=False):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for i, e in enumerate(events):
                    if outer.pause is not None and i == 2:
                        outer.pause.wait(10)
                    self.wfile.write(f"data: {json.dumps(e)}\n\n".encode())
                    self.wfile.flush()
                if done:
                    self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


MSG = [{"role": "user", "content": "hi"}]


class TestAdapters(unittest.TestCase):
    def adapters(self, url):
        return {"openai": OpenAIAdapter(base_url=url, model="m", api_key="k", max_retries=0),
                "anthropic": providers.AnthropicAdapter(url, "m", "k", max_retries=0),
                "gemini": providers.GeminiAdapter(url, "m", "k", max_retries=0)}

    def test_each_provider_streams_words_and_counts_tokens(self):
        ai = FakeAI("sse")
        try:
            for name, adapter in self.adapters(ai.url).items():
                seen = []
                text = adapter.complete_stream(MSG, seen.append)
                self.assertEqual(text, "Hello from the stream.", name)
                self.assertTrue(seen and seen[-1] == "Hello from the stream.", (name, seen))
                self.assertGreater(adapter.usage.prompt_tokens, 0, name)
                self.assertEqual(adapter.usage.calls, 1, name)
            self.assertTrue(all(streaming for _, streaming in ai.requests))
        finally:
            ai.close()

    def test_a_provider_that_ignores_streaming_still_works(self):
        ai = FakeAI("json")
        try:
            for name, adapter in self.adapters(ai.url).items():
                self.assertEqual(adapter.complete_stream(MSG, lambda t: None), "Hello from the stream.", name)
                self.assertEqual(adapter.usage.calls, 1, name)
        finally:
            ai.close()

    def test_a_provider_that_refuses_streaming_falls_back_once_and_stops_asking(self):
        ai = FakeAI("reject")
        try:
            adapter = OpenAIAdapter(base_url=ai.url, model="m", api_key="k", max_retries=0)
            self.assertEqual(adapter.complete_stream(MSG, lambda t: None), "Hello from the stream.")
            first = len(ai.requests)
            self.assertEqual(adapter.complete_stream(MSG, lambda t: None), "Hello from the stream.")
            self.assertEqual(len(ai.requests) - first, 1)  # the second call went straight to a normal request
            self.assertEqual(adapter.usage.calls, 2)
        finally:
            ai.close()

    def test_a_bad_key_is_still_reported_clearly(self):
        class Deny(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"Invalid API Key"}}')

        server = ThreadingHTTPServer(("127.0.0.1", 0), Deny)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            adapter = OpenAIAdapter(base_url=f"http://127.0.0.1:{server.server_address[1]}", model="m", api_key="k", max_retries=0)
            with self.assertRaises(RuntimeError) as ctx:
                adapter.complete_stream(MSG, lambda t: None)
            self.assertIn("401", str(ctx.exception))
        finally:
            server.shutdown()
            server.server_close()


class TestLiveDraft(Base):
    def test_the_draft_is_shown_while_writing_is_cleaned_and_private_to_the_chat(self):
        gate = threading.Event()
        ai = FakeAI("sse", pause=gate)
        self.addCleanup(ai.close)
        self.ws.set_provider("fake", "openai", ai.url, "m", key="sk-test-key-12345", make_default=True)
        self.ws.model_factory = __import__("kintsugi.workspace.core", fromlist=["x"]).default_model_factory
        self.ws._models.clear()
        self.invite_and_join("sam", rooms=["team"])
        self.ws.post("secret-room", "you", "@alice tell me", human=True)
        deadline = time.time() + 10
        draft = {}
        while time.time() < deadline and not draft:
            draft = self.call("owner", "GET", "/api/state")[1].get("drafts", {})
            time.sleep(0.05)
        self.assertIn("alice", draft)
        self.assertTrue(draft["alice"].startswith("Hello"), draft)
        # sam is not in the room the agent is working in: no draft, no activity
        state = self.call("sam", "GET", "/api/state")[1]
        self.assertNotIn("alice", state["drafts"])
        gate.set()
        self.assertTrue(self.ws.wait_idle())
        self.assertNotIn("alice", self.call("owner", "GET", "/api/state")[1]["drafts"])  # cleared when the answer is posted
        self.assertEqual(self.ws.history("secret-room")[-1]["text"], "Hello from the stream.")

    def test_tool_blocks_hidden_reasoning_and_secrets_never_show_in_the_draft(self):
        ws = self.ws
        ws.keychain.set("alice", "KEY", "sk-live-secret-abcdef-123456")
        ws.set_draft("alice", 'Let me check. ```tool\n{"tool": "run_python", "args": {"code": "print(1)"}}\n```')
        with ws._lock:
            ws._busy.add("alice")
        self.assertEqual(ws.agent_drafts()["alice"], "Let me check.")
        ws.set_draft("alice", '```tool\n{"tool": "run_python", "args"')  # an unfinished tool block
        self.assertNotIn("alice", ws.agent_drafts())
        ws.set_draft("alice", "<think>planning to use sk-live-secret-abcdef-123456</think>The answer is sk-live-secret-abcdef-123456")
        self.assertEqual(ws.agent_drafts()["alice"], "The answer is [secret:KEY]")
        ws.set_draft("alice", None)
        self.assertEqual(ws.agent_drafts(), {})

    def test_streaming_can_be_switched_off_by_the_owner_only(self):
        self.invite_and_join("sam", rooms=["team"])
        self.assertEqual(self.call("sam", "POST", "/api/streaming", {"enabled": False})[0], 403)
        self.assertEqual(self.call("owner", "POST", "/api/streaming", {"enabled": False})[1], {"enabled": False})
        self.assertEqual(self.ws.get_setting("streaming"), "off")


if __name__ == "__main__":
    unittest.main()
