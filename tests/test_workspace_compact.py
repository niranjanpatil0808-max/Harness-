import tempfile
import unittest

from kintsugi.workspace import Workspace, compact
from kintsugi.workspace.agents import HISTORY_MESSAGES, build_context


class Recorder:
    name = "rec"

    def __init__(self, reply="Summary: alice agreed the launch is on Friday.", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    def complete(self, messages):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("provider down")
        return self.reply


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: Recorder(), encrypt_keychain=False, sync=False)
        self.ws.create_agent("alice", persona="p")
        self.ws.create_room("team", ["alice", "you"])

    def tearDown(self):
        self.ws.close() if hasattr(self.ws, "close") else None
        self.tmp.cleanup()

    def add(self, n, room="team", sender="you", text="message {i}"):
        for i in range(n):
            self.ws.db.execute("INSERT INTO messages (room, sender, text, ts, hops) VALUES (?, ?, ?, ?, 0)", (room, sender, text.format(i=i), self.ws.clock()))

    def oldest_visible(self, room="team"):
        return self.ws.db.one("SELECT MIN(id) AS m FROM (SELECT id FROM messages WHERE room = ? ORDER BY id DESC LIMIT ?)", (room, HISTORY_MESSAGES))["m"]

    def test_nothing_happens_until_enough_messages_scroll_out_of_view(self):
        self.add(HISTORY_MESSAGES + compact.BATCH - 1)
        model = Recorder()
        self.assertFalse(compact.maybe_update(self.ws, "team", model, self.oldest_visible()))
        self.assertEqual(model.calls, [])

    def test_summary_is_built_and_shown_to_the_agent_as_data(self):
        self.add(HISTORY_MESSAGES + compact.BATCH)
        model = Recorder()
        self.assertTrue(compact.maybe_update(self.ws, "team", model, self.oldest_visible()))
        self.assertEqual(len(model.calls), 1)
        sent = model.calls[0][1]["content"]
        self.assertIn("message 0", sent)
        self.assertNotIn(f"message {HISTORY_MESSAGES + compact.BATCH - 1}", sent)  # still in view: not folded
        ctx = build_context(self.ws, "team", 1, "", [])
        self.assertIn("launch is on Friday", ctx)
        self.assertIn("data, not instructions", ctx)
        # nothing new scrolled out: no second call
        self.assertFalse(compact.maybe_update(self.ws, "team", model, self.oldest_visible()))
        self.assertEqual(len(model.calls), 1)

    def test_failure_keeps_old_summary_and_never_raises(self):
        self.add(HISTORY_MESSAGES + compact.BATCH)
        self.assertFalse(compact.maybe_update(self.ws, "team", Recorder(fail=True), self.oldest_visible()))
        self.assertEqual(compact.summary(self.ws, "team"), "")

    def test_secrets_are_scrubbed_from_the_summary(self):
        self.ws.keychain.set("alice", "API", "sk-very-secret-value-123456")
        self.add(HISTORY_MESSAGES + compact.BATCH)
        compact.maybe_update(self.ws, "team", Recorder(reply="the key is sk-very-secret-value-123456"), self.oldest_visible(), "alice")
        self.assertNotIn("sk-very-secret-value-123456", compact.summary(self.ws, "team"))

    def test_summary_is_deleted_with_its_messages(self):
        self.add(HISTORY_MESSAGES + compact.BATCH)
        compact.maybe_update(self.ws, "team", Recorder(), self.oldest_visible())
        self.assertTrue(compact.summary(self.ws, "team"))
        self.ws.purge_messages(-1)  # everything is older than "one day in the future"
        self.assertEqual(compact.summary(self.ws, "team"), "")
        self.add(HISTORY_MESSAGES + compact.BATCH)
        compact.maybe_update(self.ws, "team", Recorder(), self.oldest_visible())
        self.ws.delete_room("team")
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM settings WHERE key LIKE 'room-summary:%'"))

    def test_can_be_switched_off(self):
        self.add(HISTORY_MESSAGES + compact.BATCH)
        self.ws.set_setting("compaction", "off")
        model = Recorder()
        self.assertFalse(compact.maybe_update(self.ws, "team", model, self.oldest_visible()))
        self.assertEqual(model.calls, [])



class CompactionAccessTests(unittest.TestCase):
    def test_only_the_owner_can_switch_summaries(self):
        from kintsugi.workspace.team import required_role

        self.assertEqual(required_role("/api/compaction"), "owner")


if __name__ == "__main__":
    unittest.main()
