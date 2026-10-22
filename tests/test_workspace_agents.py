import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from kintsugi.memory import MemoryStore
from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.agents import parse_reply
from kintsugi.workspace.scheduler import Scheduler, cron_matches, parse_cron


def tool(name, **args):
    return "```tool\n" + json.dumps({"tool": name, "args": args}) + "\n```"


class TestParseReply(unittest.TestCase):
    def test_tool_block_and_plain_text(self):
        calls, plain = parse_reply("Let me save that.\n" + tool("remember", text="hi") + "\nthen done")
        self.assertEqual(calls, [{"tool": "remember", "args": {"text": "hi"}}])
        self.assertIn("Let me save that.", plain)

    def test_json_label_and_unlabelled_blocks_work_if_they_name_a_tool(self):
        calls, _ = parse_reply('```json\n{"tool": "list_files", "args": {}}\n```')
        self.assertEqual(calls[0]["tool"], "list_files")
        calls, _ = parse_reply('```\n{"tool": "list_files"}\n```')
        self.assertEqual(calls[0]["args"], {})

    def test_code_examples_are_not_tool_calls(self):
        reply = "Here is code:\n```python\nprint('hi')\n```\nand data:\n```json\n{\"a\": 1}\n```"
        calls, plain = parse_reply(reply)
        self.assertEqual(calls, [])
        self.assertIn("print('hi')", plain)

    def test_broken_tool_block_is_reported(self):
        calls, _ = parse_reply("```tool\n{not json}\n```")
        self.assertIn("_error", calls[0])
        calls, _ = parse_reply('```tool\n{"args": {}}\n```')
        self.assertIn("_error", calls[0])

    def test_several_calls(self):
        calls, _ = parse_reply(tool("list_files") + "\n" + tool("remember", text="x"))
        self.assertEqual([c["tool"] for c in calls], ["list_files", "remember"])


def scripted(replies, lesson="When a file may not exist, list the folder before reading it."):
    """Answer reflection prompts with `lesson` and everything else from `replies` in order."""
    queue = list(replies)

    def reply(messages):
        if "general lesson" in messages[-1]["content"]:
            return lesson
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return MockModel(reply)


class TestAgentRuns(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def workspace(self, model, **agent):
        ws = Workspace(self.tmp.name, model_factory=lambda name: model, encrypt_keychain=False)
        ws.create_agent("alice", **agent)
        ws.create_room("general", ["alice", "you"])
        return ws

    def test_agent_uses_a_tool_then_answers(self):
        model = scripted([tool("write_file", path="todo.txt", content="buy milk"), "Saved your todo."])
        ws = self.workspace(model)
        ws.post("general", "you", "@alice write a todo")
        self.assertEqual((ws.files_dir("alice") / "todo.txt").read_text(), "buy milk")
        self.assertEqual(ws.history("general")[-1]["text"], "Saved your todo.")
        # the second prompt carried the tool result back to the model
        self.assertIn("wrote todo.txt", model.prompts[1][-1]["content"])
        ws.close()

    def test_done_means_no_extra_message(self):
        model = scripted([tool("send_message", text="hello room"), "DONE"])
        ws = self.workspace(model)
        ws.post("general", "you", "@alice greet")
        self.assertEqual([m["text"] for m in ws.history("general")][1:], ["hello room"])
        ws.close()

    def test_a_failed_tool_call_becomes_a_lesson_that_is_shown_and_kept(self):
        model = scripted([tool("read_file", path="missing.txt"),
                          tool("list_files"),
                          "The file does not exist, so I listed the folder."])
        ws = self.workspace(model)
        ws.post("general", "you", "@alice read missing.txt for me")
        lessons = MemoryStore.load(ws.lessons_path("alice"))
        self.assertEqual(len(lessons.lessons), 1)
        self.assertIn("list the folder", lessons.lessons[0].text)
        # shown to the model right after the failure ...
        self.assertTrue(any("Lesson from this failure" in p[-1]["content"] for p in model.prompts))
        # ... and the run recovered, so the lesson counts as a win
        self.assertEqual((lessons.lessons[0].uses, lessons.lessons[0].wins, lessons.lessons[0].status),
                         (1, 1, "promoted"))
        ws.close()

    def test_lessons_from_earlier_runs_appear_in_later_prompts(self):
        ws = self.workspace(scripted(["fine"]))
        memory = MemoryStore.load(ws.lessons_path("alice"))
        memory.add("When asked to read a report, check the folder listing first.", "ToolError",
                   {"read", "report", "folder"}, "old-task")
        memory.save()
        model = scripted(["ok"])
        ws._models["alice"] = model
        ws.post("general", "you", "@alice please read the report in my folder")
        self.assertIn("check the folder listing first", model.prompts[0][1]["content"])
        ws.close()

    def test_risky_tool_waits_for_approval_and_stops_the_run(self):
        model = scripted([tool("run_python", code="print(40 + 2)"), "unreachable"])
        ws = self.workspace(model)
        ws.post("general", "you", "@alice compute")
        self.assertIn("I need approval", ws.history("general")[-1]["text"])
        approval = ws.approvals()[0]
        self.assertEqual(ws.decide(approval["id"], True), "42")
        self.assertIn("42", ws.history("general")[-1]["text"])
        # a run that is waiting has no outcome, so nothing was learned or punished
        self.assertEqual(MemoryStore.load(ws.lessons_path("alice")).lessons, [])
        ws.close()

    def test_runaway_tool_loop_stops_after_the_step_limit(self):
        ws = self.workspace(scripted([tool("list_files")]))
        ws.post("general", "you", "@alice go")
        self.assertIn("stopped after", ws.history("general")[-1]["text"])
        ws.close()

    def test_unreadable_tool_block_is_fed_back_to_the_model(self):
        model = scripted(["```tool\n{oops}\n```", "sorry, answering directly"])
        ws = self.workspace(model)
        ws.post("general", "you", "@alice hi")
        self.assertIn("could not read the tool block", model.prompts[1][-1]["content"])
        ws.close()

    def test_agent_to_agent_conversation_through_a_room(self):
        ws = Workspace(self.tmp.name, encrypt_keychain=False, model_factory=lambda name: {
            "alice": scripted(["@bob can you review this?"]),
            "bob": scripted(["Looks good to me, alice."]),
        }[name])
        for name in ("alice", "bob"):
            ws.create_agent(name)
        ws.create_room("general", ["alice", "bob", "you"])
        ws.post("general", "you", "@alice ask bob for a review")
        self.assertEqual([m["sender"] for m in ws.history("general")], ["you", "alice", "bob"])
        ws.close()

    def test_agents_keep_separate_files_notes_and_lessons(self):
        ws = self.workspace(scripted(["ok"]))
        ws.create_agent("bob")
        ws.add_note("alice", "alice likes tea")
        self.assertEqual(ws.search_notes("bob", "tea"), [])
        self.assertEqual(len(ws.search_notes("alice", "tea")), 1)
        self.assertNotEqual(ws.files_dir("alice"), ws.files_dir("bob"))
        ws.close()


class TestCron(unittest.TestCase):
    def test_valid_expressions(self):
        self.assertEqual(parse_cron("*/15 * * * *")[0], {0, 15, 30, 45})
        self.assertEqual(parse_cron("0 9 * * 1-5")[4], {1, 2, 3, 4, 5})
        self.assertEqual(parse_cron("0,30 8-10 1 1 7")[4], {0})  # 7 means Sunday
        self.assertEqual(parse_cron("5/20 * * * *")[0], {5, 25, 45})

    def test_invalid_expressions(self):
        for bad in ("", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *", "5-2 * * * *", "* * 0 * *"):
            with self.assertRaises(ValueError, msg=bad):
                parse_cron(bad)

    def test_matching(self):
        monday_9 = datetime(2026, 10, 26, 9, 0)  # a Monday
        saturday_9 = datetime(2026, 10, 24, 9, 0)
        self.assertTrue(cron_matches("0 9 * * 1-5", monday_9))
        self.assertFalse(cron_matches("0 9 * * 1-5", saturday_9))
        self.assertFalse(cron_matches("1 9 * * *", monday_9))
        self.assertTrue(cron_matches("0 9 * * 6", saturday_9))
        self.assertTrue(cron_matches("0 9 * * 0", datetime(2026, 10, 25, 9, 0)))  # a Sunday

    def test_day_of_month_or_weekday_when_both_are_set(self):
        # standard cron: "on the 1st OR on Mondays"
        self.assertTrue(cron_matches("0 0 1 * 1", datetime(2026, 11, 1, 0, 0)))   # a Sunday, the 1st
        self.assertTrue(cron_matches("0 0 1 * 1", datetime(2026, 11, 2, 0, 0)))   # a Monday, the 2nd
        self.assertFalse(cron_matches("0 0 1 * 1", datetime(2026, 11, 3, 0, 0)))  # a Tuesday


class TestScheduler(unittest.TestCase):
    def test_job_fires_once_per_matching_minute_and_wakes_its_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp, model_factory=lambda name: MockModel(["Good morning!"]), encrypt_keychain=False)
            ws.create_agent("alice")
            ws.create_room("general", ["alice", "you"])
            job = ws.add_job("alice", "general", "0 9 * * *", "say good morning")
            nine = datetime(2026, 10, 26, 9, 0, 5).timestamp()
            sched = Scheduler(ws)
            self.assertEqual(sched.tick(nine), 1)
            self.assertEqual(sched.tick(nine + 20), 0)  # same minute: no second fire
            self.assertEqual(sched.tick(nine + 60), 0)  # 09:01 does not match
            texts = [(m["sender"], m["text"]) for m in ws.history("general")]
            self.assertEqual(texts, [(f"cron-{job}", "@alice say good morning"), ("alice", "Good morning!")])
            next_day = datetime(2026, 10, 27, 9, 0, 1).timestamp()
            self.assertEqual(sched.tick(next_day), 1)
            ws.close()

    def test_disabled_and_broken_jobs_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp, model_factory=lambda name: MockModel(["x"]), encrypt_keychain=False)
            ws.create_agent("alice")
            ws.create_room("general", ["alice"])
            job = ws.add_job("alice", "general", "* * * * *", "ping")
            ws.db.execute("UPDATE jobs SET enabled = 0 WHERE id = ?", (job,))
            ws.db.execute("INSERT INTO jobs (agent, room, cron, prompt) VALUES ('alice', 'general', 'garbage', 'x')")
            self.assertEqual(Scheduler(ws).tick(datetime(2026, 10, 26, 9, 0).timestamp()), 0)
            ws.close()

    def test_agent_can_schedule_itself_with_approval_and_job_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = scripted([tool("schedule", cron="0 9 * * 1-5", prompt="daily standup"), "scheduled"])
            ws = Workspace(tmp, model_factory=lambda name: model, encrypt_keychain=False)
            ws.create_agent("alice")
            ws.create_room("general", ["alice", "you"])
            ws.post("general", "you", "@alice schedule a standup")
            ws.decide(ws.approvals()[0]["id"], True)
            self.assertEqual([j["cron"] for j in ws.list_jobs("alice")], ["0 9 * * 1-5"])
            for _ in range(9):
                ws.add_job("alice", "general", "0 1 * * *", "x")
            from kintsugi.workspace.tools import Ctx, execute

            ws.set_tier("alice", "dangerous")
            out = execute(Ctx(ws, "alice", "general", 1, "t"), "schedule", {"cron": "0 2 * * *", "prompt": "y"})
            self.assertEqual(out.status, "error")
            ws.close()


if __name__ == "__main__":
    unittest.main()
