import io
import json
import unittest
from unittest import mock

from kintsugi.model import THINK_RE, MockModel, OpenAIAdapter


class TestMockModel(unittest.TestCase):
    def test_replays_in_order_then_repeats_last(self):
        model = MockModel(["a", "b"])
        replies = [model.complete([{"role": "user", "content": "x"}]) for _ in range(3)]
        self.assertEqual(replies, ["a", "b", "b"])
        self.assertEqual(model.usage.calls, 3)

    def test_callable_script(self):
        model = MockModel(lambda messages: messages[-1]["content"].upper())
        self.assertEqual(model.complete([{"role": "user", "content": "hi"}]), "HI")

    def test_think_blocks_are_removed(self):
        self.assertEqual(THINK_RE.sub("", "<think>hmm\nlet me see</think>```python\nx = 1\n```").strip(),
                         "```python\nx = 1\n```")


class TestAdapterRequest(unittest.TestCase):
    def test_request_has_custom_user_agent_and_auth(self):
        reply = io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())
        with mock.patch("urllib.request.urlopen", return_value=reply) as urlopen:
            model = OpenAIAdapter(base_url="http://x/v1", model="m", api_key="secret-key")
            self.assertEqual(model.complete([{"role": "user", "content": "hi"}]), "ok")
        request = urlopen.call_args[0][0]
        self.assertTrue(request.get_header("User-agent").startswith("kintsugi/"))
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(request.full_url, "http://x/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
