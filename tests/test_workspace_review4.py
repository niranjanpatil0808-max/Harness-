"""Regression tests for the fourth review round: retry-safe sending, deleted messages reaching open screens, a deleted task title,
names of removed people, and what the live draft preview hides."""
import time

from kintsugi.workspace import Workspace
from tests.test_workspace_team import Base


class TestSayIsSafeToRetry(Base):
    def test_the_same_client_id_posts_once(self):
        first = self.call("owner", "POST", "/api/say", {"room": "team", "text": "hello once", "cid": "abc123"})[1]
        again = self.call("owner", "POST", "/api/say", {"room": "team", "text": "hello once", "cid": "abc123"})[1]
        self.assertEqual(again["id"], first["id"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(len([m for m in self.ws.history("team") if m["text"] == "hello once"]), 1)

    def test_ids_are_per_person_and_a_failed_post_can_be_retried(self):
        self.invite_and_join("sam", rooms=["team"])
        a = self.call("owner", "POST", "/api/say", {"room": "team", "text": "mine", "cid": "same"})[1]
        b = self.call("sam", "POST", "/api/say", {"room": "team", "text": "theirs", "cid": "same"})[1]
        self.assertNotEqual(a["id"], b["id"])  # somebody else's id never swallows a message
        self.assertEqual(self.call("sam", "POST", "/api/say", {"room": "secret-room", "text": "no", "cid": "zzz"})[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/say", {"room": "team", "text": "now fine", "cid": "zzz"})[0], 200)  # the refusal did not use the id up


class TestDeletedMessages(Base):
    def test_other_open_screens_are_told_which_messages_are_gone(self):
        self.invite_and_join("sam", rooms=["team"])
        mid = self.call("sam", "POST", "/api/say", {"room": "team", "text": "oops wrong channel"})[1]["id"]
        self.assertEqual(self.call("sam", "POST", "/api/message/delete", {"id": mid})[0], 200)
        seen = self.call("owner", "GET", "/api/state")[1]["deleted"]
        self.assertIn({"room": "team", "id": mid}, seen)
        # people who are not in that room are never told anything about it
        self.invite_and_join("kim", rooms=[])
        self.assertEqual(self.call("kim", "GET", "/api/state")[1]["deleted"], [])

    def test_a_deleted_message_does_not_leave_its_words_in_the_task_board(self):
        self.invite_and_join("sam", rooms=["team"])
        task = self.call("sam", "POST", "/api/tasks/create", {"room": "team", "agent": "alice", "title": "wire the money to account 12345"})[1]
        self.assertTrue(self.ws.wait_idle())
        self.call("sam", "POST", "/api/message/delete", {"id": task["message_id"] or self.ws.db.one("SELECT message_id FROM tasks WHERE id = ?", (task["id"],))["message_id"]})
        titles = [t["title"] for t in self.call("owner", "GET", "/api/tasks")[1]]
        self.assertNotIn("wire the money to account 12345", " ".join(titles))


class TestNames(Base):
    def test_a_removed_persons_name_cannot_be_taken_over_while_their_messages_remain(self):
        self.invite_and_join("carol", rooms=["team"])
        self.call("carol", "POST", "/api/say", {"room": "team", "text": "my old message"})
        self.call("owner", "POST", "/api/team/remove", {"name": "carol"})
        status, invite = self.call("owner", "POST", "/api/team/invite", {"role": "member", "rooms": ["team"]})
        status, out = self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "carol"})
        self.assertEqual(status, 400)
        self.assertIn("before", out["error"])


class TestDraftPreview(Base):
    def draft(self, text):
        self.ws.set_draft("alice", text)
        with self.ws._lock:
            self.ws._busy.add("alice")
        return self.ws.agent_drafts().get("alice", "")

    def test_calls_in_any_spelling_and_hidden_thoughts_stay_out(self):
        self.assertEqual(self.draft('Ok.\n```TOOL\n{"tool": "x", "args": {}}\n```'), "Ok.")
        self.assertEqual(self.draft('Checking.\nwrite_file {"path": "a", "content": "secret plan"}'), "Checking.")
        self.assertEqual(self.draft("x <thinking>private</thinking>y"), "x y")
        self.assertEqual(self.draft("<|channel|>analysis<|message|>hmm<|channel|>final<|message|>The answer"), "The answer")
        self.assertEqual(self.draft("Plain {braces} are fine."), "Plain {braces} are fine.")

    def test_a_hostile_run_of_spaces_is_cheap(self):
        started = time.time()
        for _ in range(20):
            self.draft("```" + " " * 30000 + "x")
        self.assertLess(time.time() - started, 2.0)
