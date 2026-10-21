import tempfile
import unittest
from pathlib import Path

from kintsugi.loop import load_task, solve
from kintsugi.memory import MemoryStore, tokens
from kintsugi.model import MockModel

FIXTURE = Path(__file__).parent / "fixtures" / "add_bug"
WRONG = "```python\n# file: calc.py\ndef add(a, b):\n    return a * b\n```"
RIGHT = "```python\n# file: calc.py\ndef add(a, b):\n    return a + b\n```"
LESSON = "When a function combines two numbers, check which arithmetic operator the description asks for."


def scripted(lesson=LESSON, fixes=(WRONG, RIGHT)):
    """Mock that answers reflection prompts with `lesson` and fix prompts with `fixes` in order."""
    fixes = list(fixes)

    def reply(messages):
        if "general lesson" in messages[-1]["content"]:
            return lesson
        return fixes.pop(0) if len(fixes) > 1 else fixes[0]

    return MockModel(reply)


class TestStore(unittest.TestCase):
    def test_tokens_split_identifiers(self):
        self.assertEqual(tokens("total_price maxLength"), {"total", "price", "max", "length"})

    def test_dedup_merges_near_duplicates(self):
        store = MemoryStore()
        store.add(LESSON, "AssertionError", {"add"}, "t1")
        store.add(LESSON + " Always.", "AssertionError", {"plus"}, "t2")
        self.assertEqual(len(store.lessons), 1)
        self.assertEqual(store.lessons[0].seen, 2)
        self.assertIn("plus", store.lessons[0].keywords)

    def test_distinct_lessons_kept(self):
        store = MemoryStore()
        store.add(LESSON, "AssertionError", set(), "t1")
        store.add("When slicing lists, remember the end index is exclusive.", "IndexError", set(), "t2")
        self.assertEqual(len(store.lessons), 2)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(Path(tmp) / "lessons.json")
            store.add(LESSON, "AssertionError", {"add"}, "t1")
            store.save()
            loaded = MemoryStore.load(Path(tmp) / "lessons.json")
            self.assertEqual(loaded.lessons[0].text, LESSON)

    def test_promote_and_prune(self):
        store = MemoryStore()
        good = store.add(LESSON, "AssertionError", set(), "t1")
        bad = store.add("When unsure, rewrite everything from scratch quickly.", "X", set(), "t1")
        store.record_outcome([good.id], True, "t2")
        for task in ("t3", "t4", "t5"):
            store.record_outcome([bad.id], False, task)
        self.assertEqual(good.status, "promoted")
        self.assertEqual(bad.status, "pruned")
        self.assertNotIn(bad, store.active)


class TestRetrieval(unittest.TestCase):
    def setUp(self):
        self.task = load_task(FIXTURE)

    def test_relevant_lesson_retrieved(self):
        store = MemoryStore()
        store.add(LESSON, "AssertionError", {"add", "sum"}, "other_task")
        store.add("When parsing dates, check the month range.", "ValueError", {"date"}, "other_task")
        found = store.retrieve(self.task)
        self.assertEqual([lesson.text for lesson in found], [LESSON])

    def test_task_never_sees_its_own_lesson(self):
        store = MemoryStore()
        store.add(LESSON, "AssertionError", {"add"}, self.task.id)
        self.assertEqual(store.retrieve(self.task), [])


class TestLoopWithMemory(unittest.TestCase):
    def setUp(self):
        self.task = load_task(FIXTURE)

    def test_failure_writes_lesson_and_shows_it_on_retry(self):
        store = MemoryStore()
        model = scripted()
        result = solve(self.task, model, max_retries=3, memory=store)
        self.assertTrue(result.passed)
        self.assertEqual(len(store.lessons), 1)
        retry_prompt = model.prompts[-1][-1]["content"]
        self.assertIn("Lesson from this failure", retry_prompt)
        # The lesson was shown and the task then passed, so it is promoted.
        self.assertEqual(store.lessons[0].status, "promoted")

    def test_lessons_injected_into_first_prompt(self):
        store = MemoryStore()
        store.add(LESSON, "AssertionError", {"add"}, "other_task")
        model = scripted(fixes=[RIGHT])
        solve(self.task, model, max_retries=3, memory=store)
        self.assertIn(LESSON, model.prompts[0][-1]["content"])

    def test_frozen_memory_does_not_learn(self):
        store = MemoryStore()
        solve(self.task, scripted(), max_retries=3, memory=store, learn=False)
        self.assertEqual(store.lessons, [])


if __name__ == "__main__":
    unittest.main()
