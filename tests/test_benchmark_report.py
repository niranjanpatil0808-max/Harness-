import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmark"))
from run_benchmark import summarize, table  # noqa: E402


def task(task_id, passed, difficulty="easy", attempts=1, scored=True, calls=1, tokens=100, errors=()):
    return {"task_id": task_id, "scored": scored, "passed": passed, "difficulty": difficulty,
            "num_attempts": attempts, "usage": {"calls": calls, "tokens": tokens}, "error_types": list(errors)}


class TestSummarize(unittest.TestCase):
    def test_complete_run(self):
        run = {"tasks": [task("a", True), task("b", False), task("h", True, "hard"),
                         task("w", False, scored=False, calls=9, tokens=900)]}
        s = summarize([run], n_heldout=3)
        self.assertAlmostEqual(s["pass_rate_mean"], 2 / 3)
        self.assertEqual(s["hard_pass_rate_mean"], 1.0)
        self.assertEqual(s["calls_scored"], 3)  # the warmup task's 9 calls are not counted

    def test_run_that_stopped_early_is_not_a_result(self):
        run = {"tasks": [task("a", False), task("b", False)]}
        s = summarize([run], n_heldout=16)
        self.assertEqual(s, {"incomplete": True, "tasks_done": 2, "tasks_total": 16})

    def test_incomplete_repeat_is_ignored_when_another_is_complete(self):
        full = {"tasks": [task("a", True), task("b", True)]}
        partial = {"tasks": [task("a", False)]}
        s = summarize([full, partial], n_heldout=2)
        self.assertEqual(s["repeats"], 1)
        self.assertEqual(s["pass_rate_mean"], 1.0)

    def test_api_errors_make_a_run_incomplete_instead_of_a_failure(self):
        run = {"tasks": [task("a", True), task("b", False, errors=["ApiError"]), task("c", True)]}
        s = summarize([run], n_heldout=3)
        self.assertEqual(s, {"incomplete": True, "tasks_done": 2, "tasks_total": 3})

    def test_old_style_per_minute_limit_errors_are_recognised(self):
        old = task("b", False, errors=["ModelError"])
        old["last_output"] = "Model API error 413: Request too large ... on tokens per minute (TPM): Limit 8000"
        run = {"tasks": [task("a", True), old]}
        self.assertEqual(summarize([run], n_heldout=2)["incomplete"], True)

    def test_table_says_incomplete(self):
        meta = {"model": "m", "mock": False, "temperature": 0.0, "modes": ["loop"], "repeats": 1,
                "split": {"heldout": ["a", "b", "c"], "hard": []}}
        data = {"meta": meta, "summary": {"loop": {"incomplete": True, "tasks_done": 1, "tasks_total": 3}}}
        self.assertIn("INCOMPLETE** (1/3 tasks answered", table(data))


if __name__ == "__main__":
    unittest.main()
