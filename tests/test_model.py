import email.message
import io
import json
import urllib.error
import unittest
from unittest import mock

from kintsugi.model import (THINK_RE, MockModel, ModelInfraError, ModelRequestError, OpenAIAdapter,
                            QuotaExhausted)


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


def http_error(code, body, headers=None):
    msg = email.message.Message()
    for key, value in (headers or {}).items():
        msg[key] = value
    return urllib.error.HTTPError("http://x", code, "err", msg, io.BytesIO(body.encode()))


class TestAdapterErrors(unittest.TestCase):
    def call(self, error):
        model = OpenAIAdapter(base_url="http://x/v1", model="m", api_key="k", max_retries=0)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            return model.complete([{"role": "user", "content": "hi"}])

    def test_request_over_the_per_minute_limit_is_an_infrastructure_error(self):
        with self.assertRaises(ModelInfraError):
            self.call(http_error(413, "Request too large ... on tokens per minute (TPM): Limit 8000"))

    def test_other_413_and_400_are_rejected_requests(self):
        for code in (400, 413, 422):
            with self.assertRaises(ModelRequestError):
                self.call(http_error(code, "context length exceeded"))

    def test_daily_quota_stops_the_run(self):
        with self.assertRaises(QuotaExhausted):
            self.call(http_error(429, "tokens per day", {"retry-after": "900"}))

    def test_short_rate_limit_that_keeps_failing_is_an_infrastructure_error(self):
        with self.assertRaises(ModelInfraError):
            self.call(http_error(429, "slow down", {"retry-after": "1"}))

    def test_bad_key_is_a_setup_error_not_a_task_failure(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.call(http_error(401, "invalid api key"))
        self.assertNotIsInstance(ctx.exception, (ModelInfraError, ModelRequestError))


if __name__ == "__main__":
    unittest.main()
