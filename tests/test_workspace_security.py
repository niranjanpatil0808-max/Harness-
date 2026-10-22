import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace, perms
from kintsugi.workspace.keychain import Keychain
from kintsugi.workspace.sandbox import PathError, run_python, safe_path
from kintsugi.workspace.tools import Ctx, execute


class TestSafePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "files"
        self.base.mkdir()
        (self.base / "ok.txt").write_text("fine")

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_paths_resolve_inside(self):
        self.assertEqual(safe_path(self.base, "ok.txt"), (self.base / "ok.txt").resolve())
        self.assertEqual(safe_path(self.base, "new/deep/file.txt").parent.name, "deep")

    def test_escapes_are_refused(self):
        for bad in ("../outside.txt", "a/../../outside.txt", "/etc/passwd", "~/x", "", "  ", "x\0y", "\\windows"):
            with self.assertRaises(PathError, msg=repr(bad)):
                safe_path(self.base, bad)

    def test_a_symlink_that_points_outside_is_refused(self):
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_text("top secret")
        (self.base / "link").symlink_to(outside)
        with self.assertRaises(PathError):
            safe_path(self.base, "link")
        (self.base / "dirlink").symlink_to(Path(self.tmp.name), target_is_directory=True)
        with self.assertRaises(PathError):
            safe_path(self.base, "dirlink/secret.txt")


class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / "files"

    def tearDown(self):
        self.tmp.cleanup()

    def test_runs_code_in_the_agent_folder(self):
        ok, out = run_python(self.folder, "import os; print(os.getcwd() == os.path.realpath('.'), os.listdir('.'))")
        self.assertTrue(ok)
        self.assertIn("True", out)

    def test_errors_are_reported(self):
        ok, out = run_python(self.folder, "raise ValueError('boom')")
        self.assertFalse(ok)
        self.assertIn("ValueError: boom", out)

    def test_infinite_loop_is_killed(self):
        ok, out = run_python(self.folder, "while True: pass", timeout=1.5)
        self.assertFalse(ok)
        self.assertIn("Timed out", out)

    def test_api_keys_in_the_server_environment_are_not_visible(self):
        with mock.patch.dict(os.environ, {"KINTSUGI_API_KEY": "sk-server-secret", "GROQ_API_KEY": "gsk_x"}):
            ok, out = run_python(self.folder, "import os; print(sorted(k for k in os.environ if 'KEY' in k))")
        self.assertEqual(out.strip(), "[]")

    def test_output_is_limited(self):
        ok, out = run_python(self.folder, "print('x' * 100000)")
        self.assertLess(len(out), 4100)

    def test_memory_limit_stops_a_memory_hog(self):
        ok, out = run_python(self.folder, "x = bytearray(3 * 1024**3)", memory_mb=512, timeout=5)
        self.assertFalse(ok)


class TestKeychain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_names_env_and_redact(self):
        kc = Keychain(Path(self.tmp.name), encrypt=False)
        kc.set("alice", "API_TOKEN", "tok-123456")
        self.assertEqual(kc.names("alice"), ["API_TOKEN"])
        self.assertEqual(kc.env_for("alice", ["API_TOKEN"]), {"API_TOKEN": "tok-123456"})
        self.assertEqual(kc.redact("alice", "the token is tok-123456!"), "the token is [secret:API_TOKEN]!")
        self.assertEqual(kc.names("bob"), [])

    def test_bad_names_empty_values_and_unknown_secrets(self):
        kc = Keychain(Path(self.tmp.name), encrypt=False)
        for bad in ("lower", "A", "HAS SPACE", "1ABC"):
            with self.assertRaises(ValueError):
                kc.set("alice", bad, "value")
        with self.assertRaises(ValueError):
            kc.set("alice", "TOKEN", "")
        with self.assertRaises(KeyError):
            kc.env_for("alice", ["NOPE"])

    def test_files_are_private(self):
        kc = Keychain(Path(self.tmp.name), encrypt=False)
        kc.set("alice", "TOKEN", "abcdef")
        mode = stat.S_IMODE((Path(self.tmp.name) / "alice.json").stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_encrypted_storage_when_the_library_is_available(self):
        try:
            import cryptography  # noqa: F401
        except ImportError:
            self.skipTest("cryptography is not installed")
        kc = Keychain(Path(self.tmp.name), encrypt=True)
        self.assertTrue(kc.encrypted)
        kc.set("alice", "TOKEN", "plain-secret-value")
        raw = (Path(self.tmp.name) / "alice.json").read_bytes()
        self.assertNotIn(b"plain-secret-value", raw)
        self.assertEqual(Keychain(Path(self.tmp.name), encrypt=True).env_for("alice", ["TOKEN"])["TOKEN"], "plain-secret-value")

    def test_without_the_library_secrets_are_plain_and_flagged(self):
        with mock.patch("kintsugi.workspace.keychain.Fernet", None):
            kc = Keychain(Path(self.tmp.name), encrypt=True)
        self.assertFalse(kc.encrypted)


class TestPermissions(unittest.TestCase):
    def test_decision_table(self):
        d = perms.decide
        self.assertEqual(d("auto", "safe", "read_file", None), perms.ALLOW)
        self.assertEqual(d("auto", "risky", "run_python", None), perms.ASK)
        self.assertEqual(d("strict", "safe", "read_file", None), perms.ASK)
        self.assertEqual(d("dangerous", "risky", "run_python", None), perms.ALLOW)
        self.assertEqual(d("dangerous", "risky", "run_python", ["read_file"]), perms.DENY)
        with self.assertRaises(ValueError):
            d("yolo", "safe", "x", None)


class TestToolExecution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda a: MockModel(["ok"]), encrypt_keychain=False)
        self.ws.create_agent("alice")
        self.ws.create_room("general", ["alice", "you"])

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def ctx(self, agent="alice"):
        return Ctx(self.ws, agent, "general", 1, "test")

    def test_auto_tier_runs_safe_tools_and_asks_for_risky_ones(self):
        out = execute(self.ctx(), "write_file", {"path": "a.txt", "content": "hi"})
        self.assertEqual(out.status, "ok")
        out = execute(self.ctx(), "run_python", {"code": "print(1)"})
        self.assertEqual(out.status, "pending")
        self.assertEqual(len(self.ws.approvals()), 1)

    def test_strict_tier_asks_for_everything_and_dangerous_for_nothing(self):
        self.ws.set_tier("alice", "strict")
        self.assertEqual(execute(self.ctx(), "list_files", {}).status, "pending")
        self.ws.set_tier("alice", "dangerous")
        self.assertEqual(execute(self.ctx(), "run_python", {"code": "print(2)"}).output, "2")

    def test_tool_allow_list_denies_everything_else(self):
        self.ws.create_agent("bob", tools=["read_file"])
        out = execute(self.ctx("bob"), "write_file", {"path": "a", "content": "b"})
        self.assertEqual(out.status, "denied")
        self.assertEqual(execute(self.ctx("bob"), "read_file", {"path": "missing"}).status, "error")

    def test_an_approval_cannot_override_the_allow_list(self):
        self.ws.create_agent("bob", tools=["read_file"])
        out = execute(self.ctx("bob"), "run_python", {"code": "print(1)"}, approved=True)
        self.assertEqual(out.status, "denied")

    def test_approving_runs_the_tool_and_tells_the_room(self):
        execute(self.ctx(), "run_python", {"code": "print(6 * 7)"})
        approval = self.ws.approvals()[0]
        self.assertEqual(self.ws.decide(approval["id"], True, by="niranjan"), "42")
        self.assertEqual(self.ws.approvals(), [])
        self.assertIn("42", self.ws.history("general")[-1]["text"])
        with self.assertRaises(Exception):
            self.ws.decide(approval["id"], True)  # a decision can only be made once

    def test_denying_does_not_run_anything(self):
        execute(self.ctx(), "write_file", {"path": "x", "content": "y"}) 
        execute(self.ctx(), "publish_app", {"name": "todo", "html": "<p>hi</p>"})
        approval = self.ws.approvals()[0]
        self.ws.decide(approval["id"], False)
        self.assertFalse((self.ws.www_dir("alice") / "todo" / "index.html").exists())

    def test_bad_arguments_and_unknown_tools(self):
        self.assertEqual(execute(self.ctx(), "nope", {}).status, "error")
        self.assertEqual(execute(self.ctx(), "read_file", "not a dict").status, "error")
        self.assertEqual(execute(self.ctx(), "read_file", {"path": 5}).status, "error")

    def test_file_tools_cannot_leave_the_folder(self):
        for tool, args in (("read_file", {"path": "../../workspace.db"}), ("write_file", {"path": "../x", "content": "y"}),
                           ("list_files", {"path": "/etc"}), ("map_project", {"path": ".."})):
            out = execute(self.ctx(), tool, args)
            self.assertEqual(out.status, "error", tool)

    def test_file_quotas(self):
        out = execute(self.ctx(), "write_file", {"path": "big.txt", "content": "x" * 300_000})
        self.assertEqual(out.status, "error")
        for i in range(25):
            execute(self.ctx(), "write_file", {"path": f"f{i}.txt", "content": "y" * 199_000})
        self.assertEqual(execute(self.ctx(), "write_file", {"path": "last.txt", "content": "z" * 199_000}).status, "error")

    def test_secrets_are_used_by_name_and_never_leak_into_output(self):
        self.ws.keychain.set("alice", "API_TOKEN", "tok-supersecret-1")
        self.ws.set_tier("alice", "dangerous")
        listing = execute(self.ctx(), "list_secrets", {})
        self.assertEqual(listing.output, "API_TOKEN")
        out = execute(self.ctx(), "run_python", {"code": "import os; print('token=' + os.environ['API_TOKEN'])",
                                                  "secrets": ["API_TOKEN"]})
        self.assertEqual(out.status, "ok")
        self.assertNotIn("tok-supersecret-1", out.output)
        self.assertIn("[secret:API_TOKEN]", out.output)
        missing = execute(self.ctx(), "run_python", {"code": "print(1)", "secrets": ["OTHER"]})
        self.assertEqual(missing.status, "error")

    def test_one_agent_cannot_use_anothers_secrets(self):
        self.ws.create_agent("bob", tier="dangerous")
        self.ws.keychain.set("alice", "API_TOKEN", "tok-supersecret-1")
        out = execute(self.ctx("bob"), "run_python", {"code": "print(1)", "secrets": ["API_TOKEN"]})
        self.assertEqual(out.status, "error")

    def test_audit_records_tool_use_without_secret_values(self):
        self.ws.keychain.set("alice", "API_TOKEN", "tok-supersecret-1")
        self.ws.set_tier("alice", "dangerous")
        execute(self.ctx(), "run_python", {"code": "print(1)", "secrets": ["API_TOKEN"]})
        log = " ".join(e["detail"] for e in self.ws.audit_log())
        self.assertNotIn("tok-supersecret-1", log)
        self.assertIn("tool-ok", [e["event"] for e in self.ws.audit_log()])


if __name__ == "__main__":
    unittest.main()
