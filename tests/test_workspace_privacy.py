import os
import socket
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace, sandbox
from kintsugi.workspace.core import BudgetExceeded, WorkspaceError
from kintsugi.workspace.tools import Ctx, execute


def force_backend(name):
    return mock.patch.multiple(sandbox, _backend=name, _backend_note="forced for the test")


class TestNamespaceSandbox(unittest.TestCase):
    def setUp(self):
        sandbox._backend = None
        if sandbox.backend() != "namespaces":
            self.skipTest("user namespaces are not available here")
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "files"
        self.folder.mkdir()
        (Path(self.tmp.name) / "secret.txt").write_text("TOP-SECRET")

    def tearDown(self):
        self.tmp.cleanup()
        sandbox._backend = None

    def run_code(self, code, **kw):
        return sandbox.run_python(self.folder, code, **kw)

    def test_code_sees_only_its_own_folder_and_cannot_read_host_files(self):
        ok, out = self.run_code(f"import os\nprint(sorted(os.listdir('/')))\nprint(os.getcwd())\n"
                                f"try:\n    print(open('{self.tmp.name}/secret.txt').read())\n"
                                "except OSError as e:\n    print('blocked', type(e).__name__)")
        self.assertTrue(ok, out)
        self.assertIn("blocked FileNotFoundError", out)
        self.assertNotIn("TOP-SECRET", out)
        self.assertIn("/work", out)
        self.assertNotIn("'home'", out)

    def test_files_written_to_the_working_folder_survive(self):
        self.assertTrue(self.run_code("open('result.txt', 'w').write('kept')")[0])
        self.assertEqual((self.folder / "result.txt").read_text(), "kept")

    def test_there_is_no_network_not_even_to_the_host_loopback(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            ok, out = self.run_code(f"import socket\ns = socket.socket(); s.settimeout(2)\n"
                                    f"try:\n    s.connect(('127.0.0.1', {port})); print('CONNECTED')\n"
                                    "except OSError as e:\n    print('no network', type(e).__name__)")
        finally:
            server.close()
        self.assertIn("no network", out)
        self.assertNotIn("CONNECTED", out)

    def test_the_system_is_read_only_and_the_server_environment_is_invisible(self):
        with mock.patch.dict(os.environ, {"KINTSUGI_API_KEY": "sk-server-key"}):
            ok, out = self.run_code("import os\ntry:\n    open('/usr/evil', 'w')\nexcept OSError as e:\n    print('ro', type(e).__name__)\n"
                                    "print([v for v in os.environ.values() if 'sk-' in v])\n"
                                    "print(len([p for p in os.listdir('/proc') if p.isdigit()]))")
        self.assertIn("ro ", out)
        self.assertIn("[]", out)  # the server's key is not in the child's environment
        self.assertLess(int(out.strip().splitlines()[-1]), 5)  # its own process list, not the host's

    def test_the_chroot_escape_trick_does_not_work(self):
        ok, out = self.run_code(f"""import os
try:
    os.mkdir('esc'); os.chroot('esc')
    for _ in range(60): os.chdir('..')
    os.chroot('.')
    print('ESCAPED', sorted(os.listdir('/'))[:5])
    print(open('{self.tmp.name}/secret.txt').read())
except OSError as e:
    print('blocked', type(e).__name__)""")
        self.assertIn("blocked PermissionError", out)
        self.assertNotIn("ESCAPED", out)
        self.assertNotIn("TOP-SECRET", out)

    def test_the_code_runs_with_no_capabilities_and_cannot_mount(self):
        ok, out = self.run_code("""import ctypes
print('caps', open('/proc/self/status').read().split('CapEff:')[1].split()[0])
libc = ctypes.CDLL(None, use_errno=True)
print('mount', libc.mount(b'none', b'/work', b'tmpfs', 0, None))
print('nonewprivs', [l for l in open('/proc/self/status') if l.startswith('NoNewPrivs')][0].strip())""")
        self.assertIn("caps 0000000000000000", out)
        self.assertIn("mount -1", out)
        self.assertIn("NoNewPrivs:\t1", out)

    def test_timeouts_and_memory_limits_still_apply(self):
        self.assertIn("Timed out", self.run_code("while True: pass", timeout=1)[1])
        ok, out = self.run_code("x = bytearray(900 * 1024 * 1024)", memory_mb=256)
        self.assertFalse(ok)
        self.assertIn("MemoryError", out)

    def test_runaway_processes_are_killed_with_the_run(self):
        ok, out = self.run_code("import subprocess, sys\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                                "import time; time.sleep(30)", timeout=1)
        self.assertIn("Timed out", out)


class TestDropUserSandbox(unittest.TestCase):
    def setUp(self):
        if os.geteuid() != 0:
            self.skipTest("needs root")
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False)
        self.ws.create_agent("alice", tier="dangerous")
        self.ws.create_agent("bob", tier="dangerous")
        self.ws.create_room("general", ["alice", "bob", "you"])
        self.ws.keychain.set("alice", "DEMO_KEY", "sk-very-secret-value")
        (self.ws.files_dir("bob") / "private.txt").write_text("bobs data")

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def test_agent_code_cannot_read_server_data_or_other_agents(self):
        probe = ("import os\nfor p in ['{r}/workspace.db', '{r}/keychain/alice.json', '{r}/token', '{r}/agents/bob/files/private.txt']:\n"
                 "    try:\n        open(p).read(); print('READ', p)\n    except OSError as e:\n        print('blocked', type(e).__name__)\n"
                 "print(os.getuid() != 0)").format(r=self.ws.root)
        with force_backend("drop-user"):
            out = execute(Ctx(self.ws, "alice", "general", 0, "t"), "run_python", {"code": probe})
        self.assertEqual(out.status, "ok", out.output)
        self.assertNotIn("READ", out.output)
        self.assertTrue(out.output.strip().endswith("True"), out.output)

    def test_data_files_are_not_world_readable(self):
        for path in (self.ws.root / "workspace.db", self.ws.keychain._path("alice")):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0, path)


class TestDataPermissions(unittest.TestCase):
    def test_folders_and_database_are_private(self):
        if os.geteuid() == 0:
            self.skipTest("as root the data root stays traversable on purpose")
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(Path(tmp) / "w", model_factory=lambda n: MockModel(["x"]), encrypt_keychain=False)
            ws.create_agent("alice")
            for path in (ws.root, ws.root / "workspace.db", ws.root / "keychain", ws.files_dir("alice"), ws.agent_dir("alice")):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode) & 0o077, 0, path)
            ws.close()


class TestDeletingData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["hello"]), encrypt_keychain=False)
        for name in ("alice", "bob"):
            self.ws.create_agent(name)
        self.ws.create_room("team", ["alice", "bob", "you"])
        self.ws.keychain.set("alice", "DEMO_KEY", "sk-very-secret-value")
        self.ws.add_note("alice", "private note")
        self.ws.add_job("alice", "team", "0 9 * * *", "x")
        (self.ws.files_dir("alice") / "a.txt").write_text("mine")
        self.ws.post("team", "you", "@alice hi")
        dm = self.ws.open_dm("you", "alice")
        self.ws.post(dm, "you", "secret chat")

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def test_deleting_an_agent_removes_everything_it_owns(self):
        self.ws.delete_agent("alice")
        self.assertIsNone(self.ws.get_agent("alice", missing_ok=True))
        self.assertFalse(self.ws.agent_dir("alice").exists())
        self.assertFalse(self.ws.keychain._path("alice").exists())
        self.assertEqual((self.ws.list_jobs("alice"), self.ws.search_notes("alice", "private note")), ([], []))
        self.assertNotIn("dm-alice-you", [r["name"] for r in self.ws.list_rooms()])
        self.assertEqual([m for m in self.ws.history("team") if m["sender"] == "alice"], [])
        self.assertNotIn("alice", self.ws.members("team"))
        self.assertIsNotNone(self.ws.get_agent("bob"))  # others untouched
        everything = repr(self.ws.db.query("SELECT * FROM messages")) + repr(self.ws.db.query("SELECT * FROM audit"))
        self.assertNotIn("secret chat", everything)

    def test_deleting_a_room_removes_its_messages_jobs_and_approvals(self):
        self.ws.request_approval("alice", "team", "run_python", {"code": "1"})
        self.ws.delete_room("team")
        self.assertNotIn("team", [r["name"] for r in self.ws.list_rooms()])
        self.assertEqual(self.ws.db.query("SELECT * FROM messages WHERE room = 'team'"), [])
        self.assertEqual((self.ws.approvals(), self.ws.list_jobs()), ([], []))

    def test_old_messages_can_be_purged(self):
        self.ws.clock = lambda: time.time() + 40 * 86400  # fast-forward 40 days
        self.ws.post("team", "you", "recent")
        self.assertGreater(self.ws.purge_messages(30), 0)
        self.assertEqual([m["text"] for m in self.ws.history("team")], ["recent"])


class TestBudget(unittest.TestCase):
    def test_runaway_conversations_stop_at_the_daily_limit(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KINTSUGI_DAILY_CALLS": "3"}):
            ws = Workspace(tmp, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False)
            ws.create_agent("alice")
            ws.create_room("r", ["alice", "you"])
            for i in range(5):
                ws.post("r", "you", f"@alice hi {i}")
            texts = [m["text"] for m in ws.history("r", limit=50) if m["sender"] != "you"]
            self.assertEqual(texts.count("ok"), 3)
            self.assertTrue(any("daily limit" in t for t in texts))
            self.assertEqual(ws.calls_today(), 3)
            ws.close()

    def test_zero_means_unlimited(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"KINTSUGI_DAILY_CALLS": "0"}):
            ws = Workspace(tmp, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False)
            for _ in range(10):
                ws.spend_call()
            ws.close()

    def test_limits_on_agents_and_rooms(self):
        from kintsugi.workspace import core

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(core, "MAX_AGENTS", 2), mock.patch.object(core, "MAX_ROOMS", 1):
            ws = Workspace(tmp, model_factory=lambda n: MockModel(["x"]), encrypt_keychain=False)
            ws.create_agent("a1")
            ws.create_agent("a2")
            with self.assertRaises(WorkspaceError):
                ws.create_agent("a3")
            ws.create_room("r1")
            with self.assertRaises(WorkspaceError):
                ws.create_room("r2")
            ws.close()


if __name__ == "__main__":
    unittest.main()
