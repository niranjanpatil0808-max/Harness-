import unittest
from pathlib import Path

from kintsugi.loop import headline, load_task, parse_files, solve
from kintsugi.model import MockModel, ModelRequestError

FIXTURE = Path(__file__).parent / "fixtures" / "add_bug"
WRONG = "```python\n# file: calc.py\ndef add(a, b):\n    return a * b\n```"
RIGHT = "```python\n# file: calc.py\ndef add(a, b):\n    return a + b\n```"


class TestParse(unittest.TestCase):
    def setUp(self):
        self.task = load_task(FIXTURE)

    def test_load_task_splits_sources_and_tests(self):
        self.assertEqual(list(self.task.sources), ["calc.py"])
        self.assertEqual(list(self.task.tests), ["test_calc.py"])

    def test_tagged_block(self):
        self.assertIn("a + b", parse_files(RIGHT, self.task)["calc.py"])

    def test_untagged_block_with_single_source(self):
        files = parse_files("Here:\n```python\ndef add(a, b):\n    return a + b\n```", self.task)
        self.assertEqual(list(files), ["calc.py"])

    def test_edits_to_tests_are_ignored(self):
        reply = "```python\n# file: test_calc.py\nprint('cheat')\n```"
        self.assertEqual(parse_files(reply, self.task), {})

    def test_unfenced_reply_is_accepted(self):
        reply = ("# file: calc.py\ndef add(a, b):\n    return a + b\n\n"
                 "# file: test_calc.py\nprint('not allowed')\n")
        files = parse_files(reply, self.task)
        self.assertEqual(list(files), ["calc.py"])  # the test file section is ignored
        self.assertIn("a + b", files["calc.py"])

    def test_unfenced_reply_with_stray_closing_fence(self):
        files = parse_files("# file: calc.py\ndef add(a, b):\n    return a + b\n```", self.task)
        self.assertEqual(files["calc.py"], "def add(a, b):\n    return a + b\n")

    def test_fenced_blocks_take_precedence_over_unfenced_text(self):
        reply = "# file: calc.py\nbogus\n\n" + RIGHT
        self.assertIn("a + b", parse_files(reply, self.task)["calc.py"])


class TestSolve(unittest.TestCase):
    def setUp(self):
        self.task = load_task(FIXTURE)

    def test_baseline_single_attempt(self):
        result = solve(self.task, MockModel([WRONG, RIGHT]), max_retries=0)
        self.assertFalse(result.passed)
        self.assertEqual(result.num_attempts, 1)

    def test_retry_with_error_feedback(self):
        model = MockModel([WRONG, RIGHT])
        result = solve(self.task, model, max_retries=3)
        self.assertTrue(result.passed)
        self.assertEqual(result.num_attempts, 2)
        # The second prompt must contain the test failure from the first attempt.
        self.assertIn("AssertionError", model.prompts[1][-1]["content"])

    def test_retry_cap(self):
        result = solve(self.task, MockModel([WRONG]), max_retries=3)
        self.assertFalse(result.passed)
        self.assertEqual(result.num_attempts, 4)

    def test_format_error_is_reported(self):
        model = MockModel(["I think you should add.", RIGHT])
        result = solve(self.task, model, max_retries=1)
        self.assertEqual(result.attempts[0].error_type, "FormatError")
        self.assertTrue(result.passed)

    def test_rejected_request_fails_the_task_without_crashing(self):
        def reply(messages):
            if len(messages) > 2:
                raise ModelRequestError("context length exceeded")
            return WRONG

        result = solve(self.task, MockModel(reply), max_retries=3)
        self.assertFalse(result.passed)
        self.assertEqual(result.attempts[-1].error_type, "ModelError")
        self.assertEqual(result.num_attempts, 2)

    def test_conversation_stays_bounded_over_many_retries(self):
        model = MockModel([WRONG])
        solve(self.task, model, max_retries=3)
        sizes = [len(messages) for messages in model.prompts]
        self.assertEqual(sizes, [2, 4, 4, 4])  # system + task, then the latest attempt and its error

    def test_earlier_failures_are_summarised(self):
        wrong_again = WRONG.replace("a * b", "a - 1")
        model = MockModel([WRONG, wrong_again, RIGHT])
        result = solve(self.task, model, max_retries=3)
        self.assertTrue(result.passed)
        third_prompt = model.prompts[2][-1]["content"]
        self.assertIn("Earlier attempts also failed", third_prompt)
        self.assertIn("attempt 1: AssertionError", third_prompt)

    def test_repeated_attempt_is_called_out(self):
        model = MockModel([WRONG, WRONG, RIGHT])
        solve(self.task, model, max_retries=3)
        self.assertIn("identical to your attempt 1", model.prompts[2][-1]["content"])

    def test_unchanged_original_is_called_out(self):
        original = "```python\n# file: calc.py\ndef add(a, b):\n    return a - b\n```"
        model = MockModel([original, RIGHT])
        solve(self.task, model, max_retries=2)
        self.assertIn("original code unchanged", model.prompts[1][-1]["content"])

    def test_headline_picks_the_exception_line(self):
        output = "FAIL: test_add\nTraceback...\nAssertionError: -1 != 5\n\nRan 1 test"
        self.assertEqual(headline(output), "AssertionError: -1 != 5")


if __name__ == "__main__":
    unittest.main()
