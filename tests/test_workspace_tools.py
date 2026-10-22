import shutil
import tempfile
import unittest
from pathlib import Path

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.tools import Ctx, execute

ROOT = Path(__file__).resolve().parent.parent
TASK = "s03_binary_search"


class TestToolsThatWrapKintsugi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        fixed = (ROOT / "benchmark" / "solutions" / TASK / "search.py").read_text()
        self.fixed_reply = f"```python\n# file: search.py\n{fixed}```"
        self.model = MockModel([self.fixed_reply])
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: self.model, encrypt_keychain=False)
        self.ws.create_agent("alice", tier="dangerous")
        self.ws.create_room("general", ["alice", "you"])
        self.project = self.ws.files_dir("alice") / "proj"
        shutil.copytree(ROOT / "benchmark" / "tasks" / TASK, self.project)

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def run_tool(self, tool, **args):
        return execute(Ctx(self.ws, "alice", "general", 0, "t"), tool, args)

    def test_fix_code_repairs_the_file_with_the_kintsugi_loop(self):
        before = (self.project / "search.py").read_text()
        out = self.run_tool("fix_code", path="proj")
        self.assertEqual(out.status, "ok", out.output)
        self.assertIn("search.py", out.output)
        self.assertNotEqual((self.project / "search.py").read_text(), before)
        # the tests were not touched
        self.assertEqual((self.project / "test_search.py").read_text(),
                         (ROOT / "benchmark" / "tasks" / TASK / "test_search.py").read_text())

    def test_fix_code_reports_failure_and_leaves_files_alone(self):
        self.model.script = ["```python\n# file: search.py\ndef binary_search(items, target):\n    return -1\n```"]
        before = (self.project / "search.py").read_text()
        out = self.run_tool("fix_code", path="proj", retries=1)
        self.assertEqual(out.status, "error")
        self.assertIn("not fixed", out.output)
        self.assertEqual((self.project / "search.py").read_text(), before)

    def test_fix_code_needs_a_task_folder_and_stays_inside_the_agent_folder(self):
        self.assertEqual(self.run_tool("fix_code", path=".").status, "error")
        self.assertEqual(self.run_tool("fix_code", path="../..").status, "error")
        (self.ws.files_dir("alice") / "broken").mkdir()
        (self.ws.files_dir("alice") / "broken" / "task.json").write_text("{not json")
        self.assertIn("bad task.json", self.run_tool("fix_code", path="broken").output)
        (self.ws.files_dir("alice") / "nodesc").mkdir()
        (self.ws.files_dir("alice") / "nodesc" / "task.json").write_text("{}")
        self.assertEqual(self.run_tool("fix_code", path="nodesc").status, "error")

    def test_map_project_describes_the_call_graph(self):
        out = self.run_tool("map_project", path="proj")
        self.assertEqual(out.status, "ok", out.output)
        self.assertIn("binary_search", out.output)

    def test_map_project_on_an_empty_folder_is_a_clear_error(self):
        (self.ws.files_dir("alice") / "empty").mkdir()
        self.assertEqual(self.run_tool("map_project", path="empty").output, "no .py files there")

    def test_notes_round_trip_through_the_tools(self):
        self.run_tool("remember", text="the customer prefers metric units")
        self.assertIn("metric", self.run_tool("search_memory", query="which units does the customer like").output)
        self.assertEqual(self.run_tool("search_memory", query="weather").output, "nothing found")

    def test_publish_app_rejects_bad_names_and_oversized_html(self):
        self.assertEqual(self.run_tool("publish_app", name="../evil", html="x").status, "error")
        self.assertEqual(self.run_tool("publish_app", name="Big", html="x").status, "error")
        self.assertEqual(self.run_tool("publish_app", name="big", html="x" * 300_000).status, "error")
        self.assertEqual(self.run_tool("publish_app", name="ok", html="<p>hi</p>").status, "ok")

    def test_published_apps_cannot_fill_the_disk(self):
        statuses = [self.run_tool("publish_app", name=f"app{i}", html="x" * 190_000).status for i in range(40)]
        self.assertIn("error", statuses)
        self.assertLessEqual(sum(p.stat().st_size for p in self.ws.www_dir("alice").rglob("*") if p.is_file()),
                             5_000_000)


if __name__ == "__main__":
    unittest.main()
