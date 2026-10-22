import tempfile
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # lets `python -m unittest tests.<name>` find dojo_models too

from dojo_models import ALL, make_model
from kintsugi.model import MockModel
from kintsugi.workspace import dojo, sandbox
from kintsugi.workspace.dojo import Meter, run_suite

ISOLATED = sandbox.status()["isolated"]


class TestDojo(unittest.TestCase):
    def test_a_good_model_passes_everything_it_is_allowed_to_attempt(self):
        suite = run_suite(lambda agent: make_model(), isolated=ISOLATED)
        self.assertEqual(suite.pass_rate, 1.0, suite.runs[0].failures)
        self.assertEqual((suite.violations, suite.fabricated, suite.unverified), (0, 0, 0))
        self.assertEqual(suite.attempted, 6 if ISOLATED else 4)

    def test_code_scenarios_are_skipped_when_code_cannot_be_isolated(self):
        suite = run_suite(lambda agent: make_model(), isolated=False)
        skipped = [k for k, ok, sk in suite.runs[0].results if sk]
        self.assertEqual(sorted(skipped), ["arithmetic", "python"])
        self.assertEqual(suite.attempted, 4)

    def test_a_model_that_promises_but_does_not_act_fails_and_is_flagged(self):
        suite = run_suite(lambda agent: make_model(solves=set()), isolated=ISOLATED)
        passed = {k for k, (ok, total) in suite.per_scenario().items() if ok}
        self.assertEqual(passed, {"injection"})  # it does nothing, so the only thing it gets right is not obeying the trap
        self.assertGreaterEqual(suite.unverified, 1 if ISOLATED else 0)

    def test_the_injection_trap_measures_obedience_not_just_failure(self):
        resistant = run_suite(lambda a: make_model(), isolated=False)
        gullible = run_suite(lambda a: make_model(gullible=True), isolated=False)
        self.assertEqual(resistant.violations, 0)
        self.assertEqual(gullible.violations, 1)
        self.assertEqual(dict(gullible.per_scenario())["injection"], (0, 1))

    def test_the_injection_trap_never_runs_the_planted_code(self):
        # the trap runs in 'auto' tier, so the attempted code waits for approval and is never executed
        suite = run_suite(lambda a: make_model(gullible=True), isolated=False)
        self.assertEqual(suite.violations, 1)
        self.assertNotIn("PWNED", suite.runs[0].transcript.replace("PWNED.txt", ""))

    def test_a_call_budget_stops_the_study_cleanly(self):
        meter = Meter(limit=5)
        suite = run_suite(lambda agent: make_model(), repeats=3, isolated=False, meter=meter)
        self.assertEqual(meter.calls, 5)
        self.assertIn("limit of 5", suite.stopped)
        self.assertLess(suite.attempted, 12)

    def test_the_workspace_daily_cap_also_stops_a_study(self):
        used = []

        def spend():
            used.append(1)
            if len(used) > 3:
                raise RuntimeError("the daily limit of 3 model calls is used up")

        meter = Meter(spend=spend)
        suite = run_suite(lambda agent: make_model(), isolated=False, meter=meter)
        self.assertIn("daily limit", suite.stopped)

    def test_model_errors_are_counted_not_fatal(self):
        class Flaky(MockModel):
            def complete(self, messages):
                raise OSError("network down")

        meter = Meter()
        suite = run_suite(lambda agent: Flaky(["x"]), isolated=False, meter=meter)
        self.assertGreater(suite.errors, 0)
        self.assertEqual(suite.passed, 0)

    def test_the_report_is_readable_and_honest_about_skips(self):
        text = dojo.format_suite("demo", run_suite(lambda a: make_model(), isolated=False))
        self.assertIn("### demo", text)
        self.assertIn("Skipped (code is not isolated here)", text)
        self.assertIn("safety violations: **0**", text)

    def test_every_scenario_has_a_unique_key_and_the_suite_has_a_safety_trap(self):
        keys = [s.key for s in dojo.SCENARIOS]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), ALL)
        self.assertTrue(any(s.violated for s in dojo.SCENARIOS))


if __name__ == "__main__":
    unittest.main()
