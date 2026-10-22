import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kintsugi.cli import main

ROOT = Path(__file__).resolve().parent.parent


def cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(args))
    return code, out.getvalue()


class TestWorkspaceCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = str(Path(self.tmp.name) / "ws")

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_a_starter_team_once(self):
        code, out = cli("workspace", "--dir", self.dir, "init")
        self.assertEqual(code, 0)
        self.assertIn("alice and bob", out)
        self.assertNotIn("alice and bob", cli("workspace", "--dir", self.dir, "init")[1])  # not twice

    def test_say_talks_to_an_agent_with_the_mock_model(self):
        cli("workspace", "--dir", self.dir, "init")
        code, out = cli("workspace", "--dir", self.dir, "--mock", "say", "team", "@alice hello")
        self.assertEqual(code, 0)
        self.assertIn("alice: (mock model", out)

    def test_errors_are_messages_not_tracebacks(self):
        cli("workspace", "--dir", self.dir, "init")
        code, out = cli("workspace", "--dir", self.dir, "say", "nope", "hi")
        self.assertEqual(code, 1)
        self.assertIn("no such room", out)
        code, out = cli("workspace", "--dir", self.dir, "agent", "alice")
        self.assertEqual((code, "already exists" in out), (1, True))

    def test_job_and_tier_commands(self):
        cli("workspace", "--dir", self.dir, "init")
        self.assertIn("scheduled", cli("workspace", "--dir", self.dir, "job", "alice", "team", "0 9 * * *", "hi")[1])
        self.assertEqual(cli("workspace", "--dir", self.dir, "job", "alice", "team", "bad cron", "hi")[0], 1)
        self.assertIn("strict", cli("workspace", "--dir", self.dir, "tier", "alice", "strict")[1])


class TestExamples(unittest.TestCase):
    def test_the_demo_runs_offline_and_shows_the_key_behaviours(self):
        result = subprocess.run([sys.executable, str(ROOT / "examples" / "workspace_demo.py")], capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("lessons: ['When a file may not exist", "I need approval to run run_python",
                         "The demo key is 26 characters long", "Reviewed: the plan looks fine",
                         "Good morning, standup time!"):
            self.assertIn(expected, result.stdout)
        self.assertNotIn("sk-demo-super-secret-value", result.stdout)


if __name__ == "__main__":
    unittest.main()
