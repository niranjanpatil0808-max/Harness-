import tempfile
import unittest
from pathlib import Path

from kintsugi.model import MockModel, ModelInfraError
from kintsugi.workspace import Workspace
from kintsugi.workspace.core import MAX_HOPS, WorkspaceError


def make(tmp, script=None, **kwargs):
    models = {}

    def factory(agent):
        if agent not in models:
            s = (script or {}).get(agent, [f"({agent} here)"])
            models[agent] = MockModel(s)
        return models[agent]

    ws = Workspace(tmp, model_factory=factory, **kwargs)
    ws.models = models
    return ws


class TestNamesAndRooms(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = make(self.tmp.name)

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def test_agent_names_are_validated(self):
        for bad in ("Alice", "1bob", "a b", "../x", ""):
            with self.assertRaises(WorkspaceError):
                self.ws.create_agent(bad)
        self.ws.create_agent("alice")
        with self.assertRaises(WorkspaceError):
            self.ws.create_agent("alice")

    def test_unknown_tier_or_tool_is_refused(self):
        with self.assertRaises(WorkspaceError):
            self.ws.create_agent("a", tier="yolo")
        with self.assertRaises(WorkspaceError):
            self.ws.create_agent("b", tools=["read_file", "launch_missiles"])

    def test_each_agent_gets_its_own_folders(self):
        self.ws.create_agent("alice")
        self.assertTrue(self.ws.files_dir("alice").is_dir())
        self.assertTrue(self.ws.www_dir("alice").is_dir())

    def test_dm_rooms_are_reserved_and_symmetric(self):
        self.assertEqual(self.ws.open_dm("zoe", "alice"), self.ws.open_dm("alice", "zoe"))
        with self.assertRaises(WorkspaceError):
            self.ws.create_room("dm-fake")


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = make(self.tmp.name)
        for name in ("alice", "bob"):
            self.ws.create_agent(name)
        self.ws.create_room("general", ["alice", "bob", "you"])

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def senders(self, room="general"):
        return [m["sender"] for m in self.ws.history(room)]

    def test_only_mentioned_agents_answer_in_a_room(self):
        self.ws.post("general", "you", "good morning everyone")
        self.assertEqual(self.senders(), ["you"])
        self.ws.post("general", "you", "@alice are you there?")
        self.assertEqual(self.senders(), ["you", "you", "alice"])

    def test_every_message_in_a_dm_wakes_the_agent(self):
        room = self.ws.open_dm("you", "alice")
        self.ws.post(room, "you", "hello")
        self.assertEqual(self.senders(room), ["you", "alice"])

    def test_agent_not_in_the_room_is_not_woken(self):
        self.ws.create_agent("carol")
        self.ws.post("general", "you", "@carol hi")
        self.assertEqual(self.senders(), ["you"])

    def test_people_cannot_pose_as_agents(self):
        with self.assertRaises(WorkspaceError):
            self.ws.post("general", "alice", "I am alice", human=True)
        with self.assertRaises(WorkspaceError):
            self.ws.post("general", "bad name!", "hi", human=True)

    def test_an_agent_cannot_post_in_a_room_it_has_not_joined(self):
        self.ws.create_room("secret", ["bob"])
        with self.assertRaises(WorkspaceError):
            self.ws.post("secret", "alice", "hi")

    def test_empty_and_huge_messages_are_refused(self):
        with self.assertRaises(WorkspaceError):
            self.ws.post("general", "you", "   ")
        with self.assertRaises(WorkspaceError):
            self.ws.post("general", "you", "x" * 5000)

    def test_history_after_an_id(self):
        first = self.ws.post("general", "you", "one")
        self.ws.post("general", "you", "two")
        self.assertEqual([m["text"] for m in self.ws.history("general", after=first)], ["two"])


class TestLoopGuardAndErrors(unittest.TestCase):
    def test_two_agents_answering_each_other_stop_at_max_hops(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = make(tmp, script={"alice": ["@bob ping"], "bob": ["@alice pong"]})
            for name in ("alice", "bob"):
                ws.create_agent(name)
            ws.create_room("general", ["alice", "bob", "you"])
            ws.post("general", "you", "@alice start")
            agent_messages = [m for m in ws.history("general") if m["sender"] in ("alice", "bob")]
            self.assertEqual(len(agent_messages), MAX_HOPS)
            self.assertIn("loop-guard", [e["event"] for e in ws.audit_log()])
            ws.close()

    def test_model_outage_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            def boom(messages):
                raise ModelInfraError("rate limited")

            ws = make(tmp, script={"alice": boom})
            ws.create_agent("alice")
            ws.create_room("general", ["alice", "you"])
            ws.post("general", "you", "@alice hi")
            last = ws.history("general")[-1]
            self.assertEqual(last["sender"], "system")
            self.assertIn("rate limited", last["text"])
            ws.close()

    def test_runaway_agent_is_rate_limited(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = make(tmp, clock=lambda: 1000.0)
            ws.create_agent("alice")
            ws.create_room("general", ["alice", "you"])
            for _ in range(25):
                ws.post("general", "you", "@alice hi")
            replies = [m for m in ws.history("general", limit=100) if m["sender"] == "alice"]
            self.assertEqual(len(replies), 20)
            self.assertIn("rate-limited", [e["event"] for e in ws.audit_log()])
            ws.close()


class TestPersistence(unittest.TestCase):
    def test_everything_survives_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = make(tmp)
            ws.create_agent("alice", persona="kind", tier="strict")
            ws.create_room("general", ["alice", "you"])
            ws.post("general", "you", "@alice hello")
            ws.close()
            again = make(tmp)
            self.assertEqual(again.get_agent("alice")["tier"], "strict")
            self.assertEqual([m["sender"] for m in again.history("general")], ["you", "alice"])
            again.close()


if __name__ == "__main__":
    unittest.main()
