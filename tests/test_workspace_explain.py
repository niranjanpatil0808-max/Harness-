import unittest

from kintsugi.model import MockModel, ModelInfraError, QuotaExhausted
from kintsugi.workspace import Workspace
from kintsugi.workspace.explain import explain_model_error
import tempfile


class TestExplain(unittest.TestCase):
    def test_common_provider_failures_become_plain_instructions(self):
        bad_key = explain_model_error(RuntimeError("Model API error 401: '{\"error\":{\"message\":\"Invalid API Key\",\"type\":\"invalid_request_error\"}}'"))
        self.assertIn("did not accept your API key", bad_key)
        self.assertIn("Settings > Models", bad_key)
        self.assertIn("Invalid API Key", bad_key)  # the provider's own words are kept
        self.assertIn("does not know this model", explain_model_error(RuntimeError("Model API error 404: '{\"error\":{\"message\":\"The model `x` does not exist\"}}'")))
        self.assertIn("rate or daily limit", explain_model_error(QuotaExhausted("Model API error 429: '{}' (asked to wait 338s)")))
        self.assertIn("too long", explain_model_error(RuntimeError("Model API error 413: '{}'")))
        self.assertIn("problem on its side (error 503)", explain_model_error(ModelInfraError("Model API error 503: ''")))
        self.assertIn("could not reach", explain_model_error(ModelInfraError("Model API unreachable: <urlopen error [Errno 111] Connection refused>")))
        self.assertEqual(explain_model_error(RuntimeError("something odd")), "something odd")

    def test_the_chat_shows_the_explanation_and_never_the_key(self):
        class Rejecting(MockModel):
            def complete(self, messages):
                raise RuntimeError("Model API error 401: '{\"error\":{\"message\":\"Incorrect API key provided: sk-SECRETKEY-12345678\"}}'")

        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp, model_factory=lambda n: Rejecting([]), encrypt_keychain=False, sync=True)
            ws.create_agent("alice", persona="p")
            ws.create_room("team", ["alice", "you"])
            ws.keychain.set(ws.SEARCH_AGENT, "KEY", "sk-SECRETKEY-12345678")
            ws.post("team", "you", "@alice hi", human=True)
            notice = [m["text"] for m in ws.history("team") if m["sender"] == "system"][-1]
            self.assertIn("alice could not answer", notice)
            self.assertIn("did not accept your API key", notice)
            self.assertNotIn("sk-SECRETKEY", notice)
            ws.close()


if __name__ == "__main__":
    unittest.main()
