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


class TestReviewC(Base):
    def test_sandbox_output_can_never_turn_isolation_off(self):
        from kintsugi.workspace import sandbox

        if sandbox.backend() != "namespaces":
            self.skipTest("needs the namespace sandbox")
        code = "import os\nprint('namespaces unavailable' if os.getcwd() == '/work' else 'ESCAPED')"
        ok, out = sandbox.run_python(self.ws.files_dir("alice"), code)
        self.assertNotIn("ESCAPED", out)

    def test_an_approved_action_runs_for_the_person_who_asked(self):
        approval = self.ws.request_approval("alice", "team", "send_message", {"room": "secret-room", "text": "x"}, "sam-not-a-person")
        self.assertIsNone(self.ws.requester_of(f"approval#{approval}"))
        self.ws.db.execute("UPDATE approvals SET requested_by = 'you' WHERE id = ?", (approval,))
        self.assertEqual(self.ws.requester_of(f"approval#{approval}"), "you")

    def test_schedules_belong_to_who_asked_and_go_with_them(self):
        from kintsugi.workspace.tools import Ctx, execute

        self.invite_and_join("sam", rooms=["team"])
        mid = self.ws.post("team", "sam", "please schedule", human=True, wake=False)
        out = execute(Ctx(self.ws, "alice", "team", 0, f"team#{mid}"), "schedule", {"cron": "0 9 * * *", "prompt": "hi"}, approved=True)
        self.assertEqual(out.status, "ok", out.output)
        self.assertEqual(self.ws.db.one("SELECT owner FROM jobs")["owner"], "sam")
        self.call("owner", "POST", "/api/team/remove", {"name": "sam"})
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM jobs"))
        nobody = execute(Ctx(self.ws, "alice", "team", 0, "team#999999"), "schedule", {"cron": "0 9 * * *", "prompt": "hi"}, approved=True)
        self.assertNotEqual(nobody.status, "ok")

    def test_restore_leaves_private_permissions_and_skips_special_files(self):
        import io, os, stat as st, tarfile
        from kintsugi.workspace import backup

        os.mkfifo(self.ws.files_dir("alice") / "pipe")
        data = backup.snapshot(self.ws)
        names = tarfile.open(fileobj=io.BytesIO(data)).getnames()
        self.assertFalse(any(n.endswith("pipe") for n in names))
        with tempfile.TemporaryDirectory() as fresh:
            backup.unpack(data, __import__("pathlib").Path(fresh))
            self.assertEqual(st.S_IMODE(os.stat(os.path.join(fresh, "workspace.db")).st_mode), 0o600)
            self.assertEqual(st.S_IMODE(os.stat(os.path.join(fresh, "agents", "alice", "files")).st_mode), 0o700)

    def test_back_dated_files_cannot_dodge_the_folder_cap(self):
        from kintsugi.workspace.tools import Ctx, execute

        code = "import os\nfor i in range(7):\n    p=f'big{i}.bin'\n    open(p,'wb').write(b'x'*1_000_000)\n    os.utime(p,(1,1))\nos.mkfifo('p')"
        out = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "run_python", {"code": code}, approved=True)
        from kintsugi.workspace.sandbox import MAX_FOLDER_BYTES, folder_size
        self.assertLessEqual(folder_size(self.ws.files_dir("alice")), MAX_FOLDER_BYTES)
        self.assertFalse((self.ws.files_dir("alice") / "p").exists())

    def test_approvals_show_everything_and_are_never_too_long_to_read(self):
        from kintsugi.workspace.tools import Ctx, execute

        self.ws.set_tier("alice", "strict")
        out = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "run_python", {"code": "#" + "x" * 25000})
        self.assertEqual(out.status, "error")
        self.assertIn("too long", out.output)

    def test_a_template_is_never_half_made(self):
        from kintsugi.workspace import templates

        first = templates.TEMPLATES["founder"]["agents"][-1][0]
        self.invite_and_join(first, rooms=["team"])
        before = {a["name"] for a in self.ws.list_agents()} if hasattr(self.ws, "list_agents") else None
        with self.assertRaises(Exception):
            templates.apply(self.ws, "founder", "you")
        if before is not None:
            self.assertEqual({a["name"] for a in self.ws.list_agents()}, before)


class TestNotesPerChat(Base):
    def test_a_note_made_in_a_private_chat_is_not_recalled_in_the_team_room(self):
        from kintsugi.workspace.agents import build_context
        from kintsugi.workspace.tools import Ctx, execute

        dm = self.ws.open_dm("you", "alice")
        execute(Ctx(self.ws, "alice", dm, 0, dm + "#1"), "remember", {"text": "my salary is 123k"})
        execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "remember", {"text": "launch is on friday"})
        self.ws.add_note("alice", "old salary note from before notes had rooms")
        team = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "search_memory", {"query": "salary"}).output
        self.assertNotIn("123k", team)
        self.assertIn("old salary note", team)  # older notes stay visible everywhere, as before
        self.assertIn("123k", execute(Ctx(self.ws, "alice", dm, 0, dm + "#1"), "search_memory", {"query": "salary"}).output)
        self.assertNotIn("friday", execute(Ctx(self.ws, "alice", dm, 0, dm + "#1"), "search_memory", {"query": "launch friday"}).output)
        self.ws.delete_room(dm)
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM notes WHERE text LIKE '%123k%'"))


class TestFilesFromPrivateChats(Base):
    def run_tool(self, room, tool, args, approved=False):
        from kintsugi.workspace.tools import Ctx, execute

        return execute(Ctx(self.ws, "alice", room, 0, room + "#1"), tool, args, approved=approved)

    def test_a_file_written_in_a_private_chat_is_not_readable_or_listed_from_a_team_room(self):
        dm = self.ws.open_dm("you", "alice")
        self.assertEqual(self.run_tool(dm, "write_file", {"path": "salary.txt", "content": "123k"}).status, "ok")
        self.assertEqual(self.run_tool("team", "write_file", {"path": "plan.txt", "content": "launch friday"}).status, "ok")
        team_read = self.run_tool("team", "read_file", {"path": "salary.txt"})
        self.assertNotEqual(team_read.status, "ok")
        self.assertNotIn("123k", team_read.output)
        listing = self.run_tool("team", "list_files", {}).output
        self.assertIn("plan.txt", listing)
        self.assertNotIn("salary.txt", listing)
        self.assertIn("123k", self.run_tool(dm, "read_file", {"path": "salary.txt"}).output)  # still there in its own chat
        self.assertIn("plan.txt", self.run_tool(dm, "list_files", {}).output)  # shared files are visible everywhere
        # the team room cannot overwrite it to read around the rule, and writing to it from the team room is refused
        self.assertNotEqual(self.run_tool("team", "write_file", {"path": "salary.txt", "content": "x"}).status, "ok")

    def test_files_made_by_code_in_a_private_chat_get_the_same_label(self):
        dm = self.ws.open_dm("you", "alice")
        out = self.run_tool(dm, "run_python", {"code": "open('secret.csv','w').write('a,b')"}, approved=True)
        self.assertEqual(out.status, "ok", out.output)
        self.assertNotEqual(self.run_tool("team", "read_file", {"path": "secret.csv"}).status, "ok")
        # rewritten in a shared room it becomes a shared file
        self.run_tool("team", "run_python", {"code": "open('secret.csv','w').write('public now')"}, approved=True)
        self.assertEqual(self.run_tool("team", "read_file", {"path": "secret.csv"}).status, "ok")

    def test_download_follows_the_same_rule_and_deleting_the_chat_frees_the_file(self):
        self.invite_and_join("ann", role="admin", rooms=["team"])
        dm = self.ws.open_dm("you", "alice")
        self.run_tool(dm, "write_file", {"path": "private.txt", "content": "hello"})
        self.assertEqual(self.call("ann", "GET", "/api/download?agent=alice&path=private.txt")[0], 403)
        self.assertEqual(self.call("owner", "GET", "/api/download?agent=alice&path=private.txt")[0], 200)
        self.ws.delete_room(dm)
        self.assertEqual(self.run_tool("team", "read_file", {"path": "private.txt"}).status, "ok")
