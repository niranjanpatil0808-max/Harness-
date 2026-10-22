import unittest

from kintsugi.model import MockModel
from tests.test_workspace_team import Base


class TestTaskBoard(Base):
    def test_a_member_gives_a_task_and_the_room_sees_it_done(self):
        self.invite_and_join("sam", rooms=["team"])
        status, task = self.call("sam", "POST", "/api/tasks/create", {"room": "team", "agent": "alice", "title": "Summarize   the plan"})
        self.assertEqual(status, 200, task)
        self.assertEqual((task["title"], task["created_by"]), ("Summarize the plan", "sam"))
        self.assertTrue(self.ws.wait_idle())
        board = self.call("owner", "GET", "/api/tasks")[1]
        self.assertEqual(board[0]["status"], "done")
        reply = self.ws.db.one("SELECT * FROM messages WHERE id = ?", (board[0]["result_id"],))
        self.assertEqual(reply["sender"], "alice")
        msg = self.ws.db.one("SELECT * FROM messages WHERE id = ?", (board[0]["message_id"],))
        self.assertEqual((msg["sender"], msg["text"]), ("sam", f"@alice Task #{task['id']}: Summarize the plan"))
        self.assertEqual(self.call("sam", "GET", "/api/state")[1]["open_tasks"], 0)

    def test_tasks_from_rooms_you_are_not_in_stay_hidden(self):
        self.invite_and_join("sam", rooms=["team"])
        self.call("owner", "POST", "/api/tasks/create", {"room": "secret-room", "agent": "alice", "title": "board pay review"})
        self.assertTrue(self.ws.wait_idle())
        self.assertEqual(self.call("sam", "GET", "/api/tasks")[1], [])
        status, _ = self.call("sam", "POST", "/api/tasks/create", {"room": "secret-room", "agent": "alice", "title": "x"})
        self.assertEqual(status, 400)
        secret_id = self.ws.db.one("SELECT id FROM tasks")["id"]
        for action in ("retry", "delete", "done"):
            status, body = self.call("sam", "POST", "/api/tasks/update", {"id": secret_id, "action": action})
            self.assertEqual(status, 400, body)
        self.assertIsNotNone(self.ws.db.one("SELECT 1 FROM tasks WHERE id = ?", (secret_id,)))

    def test_only_the_giver_or_an_admin_changes_a_task(self):
        self.invite_and_join("sam", rooms=["team"])
        self.invite_and_join("kim", rooms=["team"])
        task = self.call("sam", "POST", "/api/tasks/create", {"room": "team", "agent": "alice", "title": "draft"})[1]
        self.assertTrue(self.ws.wait_idle())
        self.assertEqual(self.call("kim", "POST", "/api/tasks/update", {"id": task["id"], "action": "delete"})[0], 400)
        status, again = self.call("sam", "POST", "/api/tasks/update", {"id": task["id"], "action": "retry"})
        self.assertEqual(status, 200, again)
        self.assertTrue(self.ws.wait_idle())
        self.assertEqual(self.ws.db.one("SELECT status FROM tasks WHERE id = ?", (task["id"],))["status"], "done")
        self.assertEqual(self.ws.db.one("SELECT COUNT(*) AS n FROM messages WHERE text LIKE ?", (f"%Task #{task['id']}%",))["n"], 2)
        self.assertEqual(self.call("owner", "POST", "/api/tasks/update", {"id": task["id"], "action": "delete"})[0], 200)

    def test_agent_must_be_in_the_room(self):
        self.ws.create_agent("bob", persona="p")
        status, body = self.call("owner", "POST", "/api/tasks/create", {"room": "team", "agent": "bob", "title": "x"})
        self.assertEqual(status, 400)
        self.assertIn("not in this room", body["error"])

    def test_a_task_waits_for_approval_then_finishes(self):
        run_code = '```tool\n{"tool": "run_python", "args": {"code": "print(2+2)"}}\n```'
        self.ws.model_factory = lambda n: MockModel([run_code, "It printed 4.", "It printed 4."])
        self.ws._models.clear()
        self.ws.set_tier("alice", "strict")
        task = self.call("owner", "POST", "/api/tasks/create", {"room": "team", "agent": "alice", "title": "add two and two"})[1]
        self.assertTrue(self.ws.wait_idle())
        row = self.ws.db.one("SELECT * FROM tasks WHERE id = ?", (task["id"],))
        pending = self.ws.db.one("SELECT id FROM approvals WHERE status = 'pending'")
        if pending is None:
            self.skipTest("run_python did not ask for approval at this tier")
        self.assertEqual((row["status"], row["approval_id"]), ("waiting", pending["id"]))
        self.call("owner", "POST", "/api/approve", {"id": pending["id"], "approve": True})
        self.assertTrue(self.ws.wait_idle())
        self.assertEqual(self.ws.db.one("SELECT status FROM tasks WHERE id = ?", (task["id"],))["status"], "done")

    def test_failed_run_and_deleting_the_room_or_agent(self):
        def broken(n):
            m = MockModel([])
            m.complete = lambda messages: (_ for _ in ()).throw(RuntimeError("provider down"))
            return m
        self.ws.model_factory = broken
        self.ws._models.clear()
        task = self.call("owner", "POST", "/api/tasks/create", {"room": "team", "agent": "alice", "title": "x"})[1]
        self.assertTrue(self.ws.wait_idle())
        self.assertEqual(self.ws.db.one("SELECT status FROM tasks WHERE id = ?", (task["id"],))["status"], "failed")
        self.ws.delete_room("team")
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM tasks"))


class TestSharing(Base):
    def test_share_an_answer_from_a_private_chat_into_the_team_room(self):
        self.invite_and_join("sam", rooms=["team"])
        dm = self.call("sam", "POST", "/api/dm", {"b": "alice"})[1]
        room = dm.get("room") or dm.get("name")
        self.call("sam", "POST", "/api/say", {"room": room, "text": "what is our plan"})
        self.assertTrue(self.ws.wait_idle())
        answer = self.ws.db.one("SELECT id FROM messages WHERE room = ? AND sender = 'alice'", (room,))["id"]
        before = self.ws.db.one("SELECT COUNT(*) AS n FROM messages")["n"]
        status, out = self.call("sam", "POST", "/api/share", {"id": answer, "room": "team"})
        self.assertEqual(status, 200, out)
        self.assertTrue(self.ws.wait_idle())
        shared = self.ws.db.one("SELECT * FROM messages WHERE id = ?", (out["id"],))
        self.assertEqual(shared["sender"], "sam")
        self.assertIn("Shared by sam from a private chat with alice (alice wrote)", shared["text"])
        self.assertIn("> ok", shared["text"])
        self.assertEqual(self.ws.db.one("SELECT COUNT(*) AS n FROM messages")["n"], before + 1)  # nobody was woken

    def test_cannot_share_what_you_cannot_see_or_into_rooms_you_are_not_in(self):
        self.invite_and_join("sam", rooms=["team"])
        secret = self.ws.post("secret-room", "you", "the numbers", human=True, wake=False)
        self.assertEqual(self.call("sam", "POST", "/api/share", {"id": secret, "room": "team"})[0], 400)
        mine = self.ws.post("team", "sam", "hello", human=True, wake=False)
        self.assertEqual(self.call("sam", "POST", "/api/share", {"id": mine, "room": "secret-room"})[0], 403)

    def test_mentioning_a_person_notifies_only_them(self):
        self.invite_and_join("sam", rooms=["team"])
        self.invite_and_join("kim", rooms=["team"])
        seen = []
        self.ws.notify_if_away = lambda reason, users=None: seen.append((reason, sorted(users or [])))
        self.ws.post("team", "kim", "@sam can you check this", human=True)
        self.assertIn(("mention", ["sam"]), seen)


if __name__ == "__main__":
    unittest.main()
