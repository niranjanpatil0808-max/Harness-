"""Regressions for security review round 2 (new backend code)."""
import os
import tempfile
import threading
import time
import unittest

from kintsugi.model import Usage
from kintsugi.workspace import Workspace, compact
from tests.test_workspace_team import Base


class Gated:
    name = "g"

    def __init__(self):
        self.usage, self.gates, self.n = Usage(), [threading.Event() for _ in range(6)], 0

    def complete(self, messages):
        self.n += 1
        self.gates[min(self.n - 1, 5)].wait(10)
        return "reply"


class TestStopRace(Base):
    def test_a_queued_message_cannot_move_the_stop_check_or_clear_a_stop(self):
        model = Gated()
        self.ws.model_factory = lambda n: model
        self.ws._models.clear()
        self.invite_and_join("bob", rooms=["team"])
        self.ws.post("secret-room", "you", "@alice long task", human=True)
        while "alice" not in self.ws.busy():
            time.sleep(0.02)
        while model.n < 1:
            time.sleep(0.02)
        self.assertEqual(self.call("bob", "POST", "/api/stop", {"agent": "alice"})[0], 403)
        self.assertNotIn("alice", self.call("bob", "GET", "/api/state")[1]["busy"])
        self.call("bob", "POST", "/api/say", {"room": "team", "text": "@alice hi"})
        time.sleep(0.3)
        self.assertEqual(self.ws.busy_room("alice"), "secret-room")
        self.assertEqual(self.call("bob", "POST", "/api/stop", {"agent": "alice"})[0], 403)
        self.assertTrue(self.ws.request_stop("alice"))
        self.call("bob", "POST", "/api/say", {"room": "team", "text": "@alice again"})
        time.sleep(0.2)
        self.assertTrue(self.ws.stop_requested("alice"))
        for g in model.gates:
            g.set()
        self.assertTrue(self.ws.wait_idle())
        texts = [m["text"] for m in self.ws.history("secret-room")]
        self.assertIn("alice was stopped.", texts)


class SlowSummary:
    name = "s"

    def __init__(self):
        self.usage, self.entered, self.release = Usage(), threading.Event(), threading.Event()

    def complete(self, messages):
        self.entered.set()
        self.release.wait(10)
        return "Bob said something private."


class TestSummaryRace(unittest.TestCase):
    def test_a_summary_finishing_after_its_room_was_deleted_is_not_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp, model_factory=lambda n: SlowSummary(), encrypt_keychain=False, sync=False)
            ws.create_agent("alice", persona="p")
            ws.create_room("r", ["alice", "you"])
            for i in range(40):
                ws.db.execute("INSERT INTO messages (room, sender, text, ts, hops) VALUES ('r', 'you', ?, ?, 0)", (f"m{i}", ws.clock()))
            model = SlowSummary()
            t = threading.Thread(target=compact.maybe_update, args=(ws, "r", model, 35))
            t.start()
            model.entered.wait(5)
            ws.delete_room("r")
            model.release.set()
            t.join(5)
            self.assertIsNone(ws.db.one("SELECT 1 FROM settings WHERE key LIKE 'room-summary:%'"))
            ws.close()


def b64(text):
    import base64
    return base64.b64encode(text.encode()).decode()


class TestUploadPrivacy(Base):
    def test_a_file_given_in_a_private_chat_stays_in_that_chat(self):
        from kintsugi.workspace.tools import Ctx, execute

        self.invite_and_join("carol", rooms=["team"])
        self.invite_and_join("ann", role="admin", rooms=["team"])
        dm = self.call("carol", "POST", "/api/dm", {"b": "alice"})[1]["room"]
        status, out = self.call("carol", "POST", "/api/upload", {"agent": "alice", "room": dm, "name": "diagnosis.txt", "data": b64("PRIVATE")})
        self.assertEqual(status, 200, out)
        # the agent sees it in carol's chat, not in the team room
        self.assertIn("PRIVATE", execute(Ctx(self.ws, "alice", dm, 0, dm + "#1"), "read_file", {"path": "uploads/diagnosis.txt"}).output)
        other = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "read_file", {"path": "uploads/diagnosis.txt"})
        self.assertNotEqual(other.status, "ok")
        self.assertNotIn("PRIVATE", other.output)
        # the admin, who is not in the chat, cannot download it; carol can
        q = f"/api/download?agent=alice&path=uploads/diagnosis.txt&room={dm}"
        self.assertEqual(self.call("ann", "GET", q)[0], 403)
        self.assertEqual(self.call("carol", "GET", q)[0], 200)
        # members cannot upload into chats they are not in, nor agents' private folders be reached by admin download of uploads without a room
        self.assertEqual(self.call("ann", "POST", "/api/upload", {"agent": "alice", "room": dm, "name": "x.txt", "data": b64("x")})[0], 403)
        # the agent cannot overwrite people's files
        self.assertNotEqual(execute(Ctx(self.ws, "alice", dm, 0, dm + "#1"), "write_file", {"path": "uploads/diagnosis.txt", "content": "x"}).status, "ok")
        # deleting the chat deletes its files
        self.ws.delete_room(dm)
        from kintsugi.workspace import uploads
        self.assertFalse(uploads.room_folder(self.ws, "alice", dm).exists())

    def test_uploads_do_not_follow_links_or_fill_the_agent_folder(self):
        import os
        from kintsugi.workspace import uploads

        folder = uploads.room_folder(self.ws, "alice", "team")
        folder.mkdir(parents=True)
        outside = os.path.join(self.tmp.name, "outside.txt")
        os.symlink(outside, folder / "note.txt")
        status, out = self.call("owner", "POST", "/api/upload", {"agent": "alice", "room": "team", "name": "note.txt", "data": b64("x")})
        self.assertEqual(status, 200, out)
        self.assertEqual(out["path"], "uploads/note (2).txt")
        self.assertFalse(os.path.exists(outside))
