"""Run the benchmark in every mode and write results/<run>.json and a markdown table.

Modes (ablation):
  baseline     one attempt, all files in the prompt, no memory
  loop         + up to 3 retries with the test error fed back
  loop+memory  + mistake memory (lessons learned on warmup tasks first)
  full         + context graph instead of all files

Scores are reported on the held-out tasks in split.json. Memory modes first run
the warmup tasks to collect lessons; warmup results are kept but not scored.

Examples:
  python benchmark/run_benchmark.py --model mock
  GROQ_API_KEY=... python benchmark/run_benchmark.py --model openai --repeats 1
  python benchmark/run_benchmark.py --resume results/<run>.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from kintsugi.loop import load_task, solve
from kintsugi.memory import MemoryStore
from kintsugi.model import MockModel, Model, OpenAIAdapter

ROOT = Path(__file__).parent
RESULTS = ROOT.parent / "results"
MODES = {
    "baseline": dict(max_retries=0, memory=False, use_graph=False),
    "loop": dict(max_retries=3, memory=False, use_graph=False),
    "loop+memory": dict(max_retries=3, memory=True, use_graph=False),
    "full": dict(max_retries=3, memory=True, use_graph=True),
}


def mock_model() -> Model:
    """Pipeline smoke test only: fails the first attempt by echoing the buggy file, then
    returns the reference fix. Its numbers say nothing about any real model."""

    def reply(messages: list[dict]) -> str:
        last = messages[-1]["content"]
        if "general lesson" in last:
            return "When tests fail, re-read the expected values in the assertion before changing code."
        first = messages[1]["content"]
        task_id = next(t for t in sorted((ROOT / "tasks").iterdir()) if t.name in first or
                       json.loads((t / "task.json").read_text())["description"] in first).name
        folder = ROOT / ("solutions" if len(messages) > 2 else "tasks") / task_id
        files = [p for p in sorted(folder.glob("*.py")) if not p.name.startswith("test_")]
        return "\n".join(f"```python\n# file: {p.name}\n{p.read_text()}```" for p in files[:1])

    return MockModel(reply)


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=ROOT).stdout.strip()
    except OSError:
        return "unknown"


def summarize(runs: list[dict]) -> dict:
    """Aggregate scored (held-out) results over repeats."""
    rates, attempts, calls, tokens = [], [], [], []
    for run in runs:
        scored = [r for r in run["tasks"] if r["scored"]]
        if not scored:
            continue
        rates.append(sum(r["passed"] for r in scored) / len(scored))
        attempts.append(statistics.mean(r["num_attempts"] for r in scored))
        calls.append(run["usage"]["calls"])
        tokens.append(run["usage"]["prompt_tokens"] + run["usage"]["completion_tokens"])
    if not rates:
        return {}
    return {
        "repeats": len(rates),
        "pass_rate_mean": statistics.mean(rates),
        "pass_rate_min": min(rates),
        "pass_rate_max": max(rates),
        "avg_attempts": statistics.mean(attempts),
        "calls_per_run": statistics.mean(calls),
        "tokens_per_run": statistics.mean(tokens),
    }


def table(data: dict) -> str:
    meta = data["meta"]
    n = len(meta["split"]["heldout"])
    lines = [
        f"Model: `{meta['model']}` · held-out tasks: {n} · max retries: 3 · temperature: {meta['temperature']}"
        + (" · **MOCK RUN (pipeline test, not a real result)**" if meta["mock"] else ""),
        "",
        "| Mode | Pass rate (held-out) | Min–max over repeats | Avg attempts | Model calls / run | Tokens / run |",
        "|---|---|---|---|---|---|",
    ]
    for mode in meta["modes"]:
        s = data["summary"].get(mode)
        if not s:
            continue
        passed = round(s["pass_rate_mean"] * n, 1)
        lines.append(
            f"| {mode} | {s['pass_rate_mean']:.0%} ({passed:g}/{n}) | {s['pass_rate_min']:.0%}–{s['pass_rate_max']:.0%} "
            f"(n={s['repeats']}) | {s['avg_attempts']:.2f} | {s['calls_per_run']:.0f} | {s['tokens_per_run']:,.0f} |"
        )
    return "\n".join(lines) + "\n"


def save(path: Path, data: dict) -> None:
    data["summary"] = {mode: summarize(data["runs"].get(mode, [])) for mode in data["meta"]["modes"]}
    path.write_text(json.dumps(data, indent=2) + "\n")
    path.with_suffix(".md").write_text(table(data))


def run_mode(data: dict, mode: str, repeat: int, model: Model, out: Path, sleep: float) -> None:
    config = MODES[mode]
    split = data["meta"]["split"]
    runs = data["runs"].setdefault(mode, [])
    while len(runs) <= repeat:
        runs.append({"repeat": len(runs), "tasks": [], "usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}})
    run = runs[repeat]
    done = {r["task_id"] for r in run["tasks"]}
    memory = None
    memory_path = out.parent / f"{out.stem}.lessons.{mode}.r{repeat}.json"
    if config["memory"]:
        memory = MemoryStore.load(memory_path)  # resumes the lessons of an interrupted run
    order = (split["warmup"] if config["memory"] else []) + split["heldout"]
    for task_id in order:
        if task_id in done:
            continue
        task = load_task(ROOT / "tasks" / task_id)
        before = asdict(model.usage)
        result = solve(task, model, max_retries=config["max_retries"], memory=memory,
                       use_graph=config["use_graph"])
        after = asdict(model.usage)
        for key in run["usage"]:
            run["usage"][key] += after[key] - before[key]
        record = {
            "task_id": task_id,
            "kind": task.meta.get("kind"),
            "scored": task_id in split["heldout"],
            "passed": result.passed,
            "num_attempts": result.num_attempts,
            "error_types": [a.error_type for a in result.attempts if not a.passed],
            "lessons_used": result.attempts[0].lessons_used if result.attempts else [],
            "lessons_learned": result.lessons_learned,
            "last_output": "" if result.passed else result.attempts[-1].output[-600:],
        }
        run["tasks"].append(record)
        save(out, data)
        mark = "PASS" if result.passed else "fail"
        print(f"[{mode} r{repeat}] {task_id:<22} {mark} after {result.num_attempts} attempt(s)", flush=True)
        if sleep:
            time.sleep(sleep)
    if memory is not None:
        memory.path = memory_path
        memory.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["mock", "openai"], default="mock",
                        help="'openai' = any OpenAI-compatible endpoint from KINTSUGI_*/GROQ_API_KEY env vars")
    parser.add_argument("--modes", nargs="+", default=list(MODES), choices=list(MODES))
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to wait between tasks (rate limits)")
    parser.add_argument("--resume", type=Path, help="continue an interrupted results/<run>.json")
    args = parser.parse_args()

    if args.resume:
        out = args.resume
        data = json.loads(out.read_text())
    else:
        RESULTS.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out = RESULTS / f"{stamp}-{args.model}.json"
        data = {"meta": {}, "runs": {}}
        data["meta"] = {
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "git_commit": git_commit(),
            "mock": args.model == "mock",
            "modes": args.modes,
            "repeats": args.repeats,
            "temperature": 0.0,
            "split": json.loads((ROOT / "split.json").read_text()),
        }
    model = mock_model() if data["meta"]["mock"] else OpenAIAdapter(temperature=data["meta"]["temperature"])
    data["meta"]["model"] = model.name
    if not data["meta"]["mock"]:
        data["meta"]["base_url"] = model.base_url

    for repeat in range(data["meta"]["repeats"]):
        for mode in data["meta"]["modes"]:
            run_mode(data, mode, repeat, model, out, args.sleep)
    data["meta"]["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(out, data)
    print("\n" + table(data))
    print(f"Saved {out} and {out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
