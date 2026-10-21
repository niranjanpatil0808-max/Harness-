import unittest
from pathlib import Path

from kintsugi.verifier import verify

FIXTURE = Path(__file__).parent / "fixtures" / "add_bug"
FIXED = "def add(a, b):\n    return a + b\n"


class TestVerifier(unittest.TestCase):
    def test_buggy_code_fails(self):
        result = verify(FIXTURE)
        self.assertFalse(result.passed)
        self.assertEqual(result.error_type, "AssertionError")

    def test_fixed_code_passes(self):
        self.assertTrue(verify(FIXTURE, {"calc.py": FIXED}).passed)

    def test_original_task_untouched(self):
        verify(FIXTURE, {"calc.py": FIXED})
        self.assertIn("a - b", (FIXTURE / "calc.py").read_text())

    def test_infinite_loop_times_out(self):
        result = verify(FIXTURE, {"calc.py": "def add(a, b):\n    while True:\n        pass\n"}, timeout=2)
        self.assertEqual(result.error_type, "Timeout")

    def test_syntax_error_reported(self):
        result = verify(FIXTURE, {"calc.py": "def add(a, b)\n    return a + b\n"})
        self.assertFalse(result.passed)
        self.assertIn("SyntaxError", result.output)

    def test_refuses_path_escape(self):
        result = verify(FIXTURE, {"../evil.py": "x = 1"})
        self.assertEqual(result.error_type, "PathError")


if __name__ == "__main__":
    unittest.main()
