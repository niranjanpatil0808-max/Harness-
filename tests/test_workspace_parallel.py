import http.client
import json
import tempfile
import threading
import time
import unittest

from kintsugi.workspace import Workspace
from kintsugi.workspace.core import WorkspaceError
from kintsugi.workspace.server import make_server


class SlowModel:
    """Takes a while to answer and records how many calls overlap (in total and per agent)."""

    name = "slow"
    lock = threading.Lock()
    now = peak = 0
    per_agent: dict = {}

    def __init__(self, agent):
        self.agent = agent
        self.usage = None

    def complete(self, messages):
        cls = SlowModel
        with cls.lock:
            cls.now += 1
            cls.peak = max(cls.peak, cls.now)
            cls.per_agent[self.agent] = cls.per_agent.get(self.agent, 0) + 1
            mine = cls.per_agent[self.agent]
        self.mine_peak = mine
        time.sleep(0.4)
        with cls.lock:
            cls.now -= 1
            cls.per_agent[self.agent] -= 1
        return "ready"


def make(tmp, names=("alice", "bob", "carol")):
    SlowModel.now = SlowModel.peak = 0
    SlowModel.per_agent = {}
    ws = Workspace(tmp, model_factory=lambda n: SlowModel(n), encrypt_keychain=False, sync=False)
    for n in names:
        ws.create_agent(n, persona="p")
    ws.create_room("team", list(names) + ["you"])
    return ws


class TestParallel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def say(self, text):
        started = time.time()
        self.ws.post("team", "you", text, human=True)
        self.assertTrue(self.ws.wait_idle(20))
        return time.time() - started

    def replies(self):
        return sorted(m["sender"] for m in self.ws.history("team", limit=50) if m["text"] == "ready")

    def test_all_wakes_every_agent_and_they_work_at_the_same_time(self):
        self.ws = make(self.tmp.name)
        elapsed = self.say("@all summarise the plan")
        self.assertEqual(self.replies(), ["alice", "bob", "carol"])
        self.assertEqual(SlowModel.peak, 3)  # truly overlapping
        self.assertLess(elapsed, 1.0)  # three 0.4 s answers in roughly one 0.4 s, not 1.2 s

    def test_the_limit_is_respected_and_changes_take_effect(self):
        self.ws = make(self.tmp.name)
        self.assertEqual(self.ws.set_parallel(1), 1)
        elapsed = self.say("@all go")
        self.assertEqual(SlowModel.peak, 1)
        self.assertGreaterEqual(elapsed, 1.1)  # one at a time
        SlowModel.peak = 0
        self.ws.set_parallel(2)
        self.say("@all again")
        self.assertEqual(SlowModel.peak, 2)

    def test_limit_is_clamped_and_remembered(self):
        self.ws = make(self.tmp.name)
        self.assertEqual(self.ws.set_parallel(99), self.ws.MAX_PARALLEL)
        self.assertEqual(self.ws.set_parallel(0), 1)
        self.ws.set_parallel(5)
        self.ws.close()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: SlowModel(n), encrypt_keychain=False, sync=False)
        self.assertEqual(self.ws.parallel_limit(), 5)

    def test_one_agent_never_runs_twice_at_once(self):
        self.ws = make(self.tmp.name, ("alice",))
        self.ws.post("team", "you", "@alice one", human=True)
        self.ws.post("team", "you", "@alice two", human=True)
        self.assertTrue(self.ws.wait_idle(20))
        self.assertEqual(SlowModel.peak, 1)
        self.assertEqual(self.replies(), ["alice", "alice"])

    def test_all_only_reaches_members_not_the_sender_and_not_other_rooms(self):
        self.ws = make(self.tmp.name)
        self.ws.create_agent("dave", persona="p")  # not in the room
        self.say("@all hello")
        self.assertEqual(self.replies(), ["alice", "bob", "carol"])
        self.assertFalse(any(m["sender"] == "dave" for m in self.ws.history("team", limit=50)))

    def test_the_daily_cap_still_stops_parallel_work(self):
        self.ws = make(self.tmp.name)
        self.ws.daily_calls = 2
        self.say("@all go")
        texts = " ".join(m["text"] for m in self.ws.history("team", limit=50))
        self.assertIn("daily limit", texts)
        self.assertEqual(len(self.replies()), 2)

    def test_the_names_all_and_everyone_are_reserved(self):
        self.ws = make(self.tmp.name, ("alice",))
        for name in ("all", "everyone"):
            with self.assertRaises(WorkspaceError):
                self.ws.create_agent(name)

    def test_api(self):
        self.ws = make(self.tmp.name, ("alice",))
        api = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=api.serve_forever, daemon=True).start()
        try:
            def call(method, path, body=None):
                conn = http.client.HTTPConnection("127.0.0.1", api.server_port, timeout=10)
                conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": "secret-token"})
                resp = conn.getresponse()
                return resp.status, json.loads(resp.read())

            self.assertEqual(call("GET", "/api/parallel")[1]["limit"], 4)
            self.assertEqual(call("POST", "/api/parallel", {"limit": 3})[1]["limit"], 3)
            self.assertEqual(call("POST", "/api/parallel", {"limit": "many"})[0], 400)
        finally:
            api.shutdown()
            api.server_close()


if __name__ == "__main__":
    unittest.main()
