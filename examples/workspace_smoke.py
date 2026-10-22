"""Smoke test of the workspace against a REAL model (needs KINTSUGI_API_KEY; model via KINTSUGI_MODEL).

    python examples/workspace_smoke.py [--out results/workspace_smoke.md] [--repeats 3]

It runs the same practice suite the workspace uses to study itself (src/kintsugi/workspace/dojo.py): each scenario is
judged by evidence (a file on disk AND the audit log showing the tool really ran), one scenario is a prompt-injection
trap, and fabricated chat lines are counted. A scenario that needs code execution is skipped unless code can be
isolated here, or SMOKE_UNATTENDED_OK=1 says this machine is disposable (a CI runner). Small and cheap on purpose;
it is not a benchmark.
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kintsugi.model import OpenAIAdapter  # noqa: E402
from kintsugi.workspace import sandbox  # noqa: E402
from kintsugi.workspace.dojo import format_suite, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("SMOKE_REPEATS", "2")))
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("SMOKE_SLEEP", "3")))
    args = parser.parse_args()
    model_name = os.environ.get("KINTSUGI_MODEL", "(default)")
    isolated = sandbox.status()["isolated"] or os.environ.get("SMOKE_UNATTENDED_OK") == "1"
    started = time.time()
    suite = run_suite(lambda agent: OpenAIAdapter(), repeats=args.repeats, isolated=isolated, sleep=args.sleep)
    report = [f"# Workspace smoke test: {model_name}", "",
              "Real model, the workspace's own practice suite (`src/kintsugi/workspace/dojo.py`), judged by files on disk **and** the audit log "
              f"showing the tool really ran. {args.repeats} runs, {time.time() - started:.0f}s. A small check that the model can follow the "
              "plain-text tool protocol; it is not a benchmark and says nothing about lesson quality.", "", format_suite(model_name, suite), "",
              "## Transcript of the last run", "", "```", suite.runs[-1].transcript if suite.runs else "(no runs)", "```", ""]
    text = "\n".join(report)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0 if suite.passed == suite.attempted and suite.violations == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
