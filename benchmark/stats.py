"""Paired comparisons between the modes of one benchmark run (standard library only).

Every comparison is paired by task: a task's score in a mode is its pass rate over the
repeats, and the difference between two modes is averaged over tasks. The error bar is a
bootstrap over tasks (resample the tasks with replacement). It says how much the
difference could move if a different set of similar tasks had been drawn; it does not
cover run-to-run noise of the model beyond what the repeats already average out.
"""

from __future__ import annotations

import random
import statistics

BOOTSTRAPS = 4000


def is_api_error(record: dict) -> bool:
    """True if the task ended without an answer for infrastructure reasons.

    Early result files labelled the 'request over the per-minute token limit' error as ModelError,
    so that case is recognised by its message too.
    """
    if "ApiError" in record["error_types"]:
        return True
    return "ModelError" in record["error_types"] and "per minute" in record.get("last_output", "").lower()


def first_ok(record: dict) -> bool:
    """Did the very first attempt pass? (Passed at attempt 1, so num_attempts is 1.)"""
    return record["passed"] and record["num_attempts"] == 1


def complete_repeats(data: dict, mode: str) -> list[dict]:
    """The repeats of `mode` that answered every held-out task, as {task_id: record}."""
    heldout = data["meta"]["split"]["heldout"]
    complete = []
    for run in data["runs"].get(mode, []):
        scored = {r["task_id"]: r for r in run["tasks"] if r["scored"] and not is_api_error(r)}
        if len(scored) == len(heldout):
            complete.append(scored)
    return complete


def per_task(repeats: list[dict], value) -> dict[str, float]:
    return {task: statistics.mean(float(value(run[task])) for run in repeats) for task in repeats[0]}


def bootstrap_diff(a: dict[str, float], b: dict[str, float], seed: int = 1) -> tuple[float, float, float]:
    """Mean of a-b over tasks and its 95% bootstrap interval."""
    diffs = [a[t] - b[t] for t in a]
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(diffs, k=len(diffs))) for _ in range(BOOTSTRAPS))
    return statistics.mean(diffs), means[int(0.025 * BOOTSTRAPS)], means[int(0.975 * BOOTSTRAPS)]


def pp(x: float) -> str:
    return f"{x * 100:+.1f} pp"


def verdict(low: float, high: float) -> str:
    if low > 0:
        return "the interval is above zero"
    if high < 0:
        return "the interval is below zero"
    return "the interval includes zero, so this is not distinguishable from no effect"


def describe(data: dict) -> list[str]:
    """Markdown bullets for the comparisons this run can support."""
    lines: list[str] = []
    loop = complete_repeats(data, "loop")
    if loop:
        first = per_task(loop, first_ok)
        final = per_task(loop, lambda r: r["passed"])
        mean, low, high = bootstrap_diff(final, first)
        runs = [r for rep in loop for r in rep.values()]
        failed_first = [r for r in runs if not first_ok(r)]
        repaired = [r for r in failed_first if r["passed"]]
        lines.append(
            f"- **Retries (loop mode):** first attempt passes {statistics.mean(first.values()):.0%}, "
            f"after retries {statistics.mean(final.values()):.0%} ({pp(mean)}, 95% interval {pp(low)} to {pp(high)}; "
            f"{verdict(low, high)}). Of {len(runs)} task runs, {len(failed_first)} failed the first attempt "
            f"and {len(repaired)} of those were repaired by the retries. The first attempt of this mode is the "
            "same request as the no-retry baseline, so the comparison is within the same runs."
        )
    pairs = [("loop+memory", "loop", "Memory (loop+memory vs loop)"),
             ("loop+graph", "loop", "Context graph alone (loop+graph vs loop)"),
             ("full", "loop+memory", "Context graph with memory (full vs loop+memory)"),
             ("full", "loop", "Memory and graph together (full vs loop)"),
             ("loop", "baseline", "Loop vs the separate baseline mode")]
    for mode_a, mode_b, label in pairs:
        a_runs, b_runs = complete_repeats(data, mode_a), complete_repeats(data, mode_b)
        if not a_runs or not b_runs:
            continue
        a = per_task(a_runs, lambda r: r["passed"])
        b = per_task(b_runs, lambda r: r["passed"])
        mean, low, high = bootstrap_diff(a, b)
        line = (f"- **{label}:** {statistics.mean(a.values()):.0%} vs {statistics.mean(b.values()):.0%} "
                f"({pp(mean)}, 95% interval {pp(low)} to {pp(high)}; {verdict(low, high)}).")
        tokens_a = [r["usage"]["tokens"] for rep in a_runs for r in rep.values() if "usage" in r]
        tokens_b = [r["usage"]["tokens"] for rep in b_runs for r in rep.values() if "usage" in r]
        if tokens_a and tokens_b and statistics.mean(tokens_b):
            line += f" Tokens per task: {statistics.mean(tokens_a):,.0f} vs {statistics.mean(tokens_b):,.0f}."
        lines.append(line)
    return lines
