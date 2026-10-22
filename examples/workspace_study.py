"""Compare models on the workspace's practice suite, with a REAL provider (needs KINTSUGI_API_KEY).

    STUDY_MODELS="allam-2-7b qwen/qwen3.8-27b" python examples/workspace_study.py --out results/workspace_models.md

Prints one table so you can see which model uses tools most reliably before choosing it for an agent. It spends real
model calls (STUDY_MAX_CALLS is the hard limit). The suite is small: treat differences of a few points as noise.
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kintsugi.model import OpenAIAdapter  # noqa: E402
from kintsugi.workspace import sandbox  # noqa: E402
from kintsugi.workspace.dojo import Meter, format_suite, run_suite  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("STUDY_REPEATS", "1")))
    parser.add_argument("--max-calls", type=int, default=int(os.environ.get("STUDY_MAX_CALLS", "120")))
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("STUDY_SLEEP", "2")))
    args = parser.parse_args()
    models = os.environ.get("STUDY_MODELS", "").split()
    if not models:
        print("STUDY_MODELS is empty: nothing to study (no model calls were made).")
        return 0
    isolated = sandbox.status()["isolated"] or os.environ.get("SMOKE_UNATTENDED_OK") == "1"
    meter = Meter(limit=args.max_calls)
    rows, sections, started = [], [], time.time()
    for name in models:
        if meter.stopped:
            break
        suite = run_suite(lambda agent, name=name: OpenAIAdapter(model=name), repeats=args.repeats, isolated=isolated, meter=meter, sleep=args.sleep)
        s = suite.summary()
        rows.append(f"| {name} | {s['passed']}/{s['attempted']} ({s['pass_rate']:.0%}) | {s['violations']} | {s['fabricated']} | {s['unverified']} | {s['calls']} | {s['seconds']:.0f}s | {s['errors']} |")
        sections.append(format_suite(name, suite))
        print(rows[-1])
    report = ["# Which model uses tools most reliably?", "",
              f"The workspace's practice suite (`src/kintsugi/workspace/dojo.py`), {args.repeats} run(s) per model, {meter.calls} model calls in "
              f"{time.time() - started:.0f}s. Small samples: a few points of difference are noise. Unsafe actions = obeying the planted instruction.", "",
              "| Model | Passed | Unsafe actions | Fabricated | Unverified | Calls | Time | Errors |", "|---|---|---|---|---|---|---|---|", *rows, ""]
    if meter.stopped:
        report += [f"Stopped early: {meter.stopped}.", ""]
    report += ["## Details", "", *sections]
    text = "\n".join(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
