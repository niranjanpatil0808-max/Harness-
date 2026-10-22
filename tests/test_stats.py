import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmark"))
from stats import bootstrap_diff, describe, first_ok  # noqa: E402

TASKS = [f"t{i}" for i in range(12)]


def rec(task_id, passed, attempts=1, tokens=100, errors=()):
    return {"task_id": task_id, "scored": True, "passed": passed, "num_attempts": attempts,
            "error_types": list(errors), "usage": {"calls": attempts, "tokens": tokens}}


def data_with(modes):
    return {"meta": {"split": {"heldout": TASKS}}, "runs": {m: [{"tasks": ts} for ts in reps] for m, reps in modes.items()}}


class TestStats(unittest.TestCase):
    def test_first_attempt_definition(self):
        self.assertTrue(first_ok(rec("a", True, 1)))
        self.assertFalse(first_ok(rec("a", True, 2)))  # passed, but only after a retry
        self.assertFalse(first_ok(rec("a", False, 4)))

    def test_clear_gain_has_interval_above_zero(self):
        a = {t: 1.0 for t in TASKS}
        b = {t: 0.0 if i < 8 else 1.0 for i, t in enumerate(TASKS)}
        mean, low, high = bootstrap_diff(a, b)
        self.assertAlmostEqual(mean, 8 / 12)
        self.assertGreater(low, 0)

    def test_no_difference_includes_zero(self):
        a = {t: 1.0 for t in TASKS}
        mean, low, high = bootstrap_diff(a, dict(a))
        self.assertEqual((mean, low, high), (0.0, 0.0, 0.0))

    def test_retry_effect_is_counted_within_loop_runs(self):
        # 4 tasks fail the first attempt; the retries repair 3 of them.
        loop = [rec(t, True, 1) for t in TASKS[4:]] + [rec(t, True, 2) for t in TASKS[:3]] + [rec(TASKS[3], False, 4)]
        lines = describe(data_with({"loop": [loop]}))
        self.assertIn("4 failed the first attempt and 3 of those were repaired", lines[0])
        self.assertIn("first attempt passes 67%", lines[0])
        self.assertIn("after retries 92%", lines[0])

    def test_incomplete_or_api_error_runs_are_not_compared(self):
        partial = [rec(t, True) for t in TASKS[:5]]
        errored = [rec(t, True) for t in TASKS[:-1]] + [rec(TASKS[-1], False, errors=["ApiError"])]
        self.assertEqual(describe(data_with({"loop": [partial], "full": [errored]})), [])

    def test_memory_and_graph_comparisons_report_tokens(self):
        loop = [rec(t, True, tokens=200) for t in TASKS]
        mem = [rec(t, True, tokens=150) for t in TASKS]
        full = [rec(t, True, tokens=60) for t in TASKS]
        lines = describe(data_with({"loop": [loop], "loop+memory": [mem], "full": [full]}))
        text = "\n".join(lines)
        self.assertIn("Context graph with memory (full vs loop+memory)", text)
        self.assertIn("Tokens per task: 60 vs 150", text)

    def test_graph_alone_is_compared_with_the_plain_loop(self):
        loop = [rec(t, True, tokens=300) for t in TASKS]
        graph = [rec(t, True, tokens=140) for t in TASKS]
        text = "\n".join(describe(data_with({"loop": [loop], "loop+graph": [graph]})))
        self.assertIn("Context graph alone (loop+graph vs loop)", text)
        self.assertIn("Tokens per task: 140 vs 300", text)


if __name__ == "__main__":
    unittest.main()
