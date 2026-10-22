"""Smoke test of the workspace against a REAL model (needs KINTSUGI_API_KEY; model via KINTSUGI_MODEL).

    python examples/workspace_smoke.py [--out results/workspace_smoke.md] [--repeats 3]

Each scenario is judged by evidence that does not depend on trusting the model's words: a file on disk AND the
audit log showing the tool really ran (a model that just claims it did the work fails). It also counts agent
messages that contain fabricated chat lines or fake 'tool results'. Agents run in the 'dangerous' tier so that
run_python does not wait for a human. Small and cheap on purpose: it shows whether a given model can follow the
plain-text tool protocol, with a pass rate over repeats. It is not a benchmark.
"""

import argparse
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kintsugi.memory import MemoryStore  # noqa: E402
from kintsugi.model import OpenAIAdapter  # noqa: E402
from kintsugi.workspace import Workspace  # noqa: E402

FABRICATED = re.compile(r"(?im)(^\s*\[\d+\]\s*\w+:|tool results?:|<message\b|\[(?:run_python|read_file|write_file|send_message|search_memory)\]\s*(?:ok|error))")


def run_once(sleep: float) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        models = {}
        ws = Workspace(tmp, model_factory=lambda n: models.setdefault(n, OpenAIAdapter()), encrypt_keychain=False)
        ws.create_agent("alice", persona="You are a careful assistant.", tier="dangerous")
        ws.create_agent("bob", persona="You review work and answer briefly.", tier="dangerous")
        ws.create_room("team", ["alice", "bob", "you"])
        files = ws.files_dir("alice")

        def tool_ran(name, ok=True):
            wanted = "tool-ok" if ok else "tool-error"
            return any(r["event"] == wanted and r["detail"].startswith(name) and r["agent"] == "alice" for r in ws.audit_log(2000))

        def alice_said():
            return " ".join(m["text"] for m in ws.history("team", limit=500) if m["sender"] == "alice")

        scenarios = [
            ("write a file", "@alice create a file named notes.txt that contains the word hello",
             lambda: (files / "notes.txt").is_file() and "hello" in (files / "notes.txt").read_text().lower() and tool_ran("write_file")),
            ("recover from a missing file", "@alice read missing.txt. If it does not exist, create it containing the text created.",
             lambda: (files / "missing.txt").is_file() and "created" in (files / "missing.txt").read_text().lower() and tool_ran("write_file")),
            ("use python", "@alice use python to compute 17 * 23 and tell me the result.",
             lambda: "391" in alice_said() and tool_ran("run_python")),
            ("do not guess arithmetic", "@alice what is 123 * 457? Use a tool, do not guess.",
             lambda: "56211" in alice_said().replace(",", "") and tool_ran("run_python")),
            ("two agents", "@alice ask @bob to say the word pineapple.",
             lambda: any("pineapple" in m["text"].lower() for m in ws.history("team", limit=500) if m["sender"] == "bob")),
        ]
        results = []
        for title, prompt, check in scenarios:
            before = sum(m.usage.calls for m in models.values())
            ws.post("team", "you", prompt, human=True)
            calls = sum(m.usage.calls for m in models.values()) - before
            try:
                ok = bool(check())
            except OSError:
                ok = False
            results.append((title, ok, calls))
            time.sleep(sleep)
        agent_texts = [m["text"] for m in ws.history("team", limit=500) if m["sender"] in ("alice", "bob")]
        out = {"results": results, "fabricated": sum(1 for t in agent_texts if FABRICATED.search(t)), "messages": len(agent_texts),
               "errors": sum(1 for r in ws.audit_log(2000) if r["event"] == "run-error"),
               "lessons": [l.text for l in MemoryStore.load(ws.lessons_path("alice")).lessons],
               "transcript": "\n".join(f"{m['sender']:>8}: {' '.join(m['text'].split())[:300]}" for m in ws.history("team", limit=500))}
        ws.close()
        return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--repeats", type=int, default=int(os.environ.get("SMOKE_REPEATS", "2")))
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("SMOKE_SLEEP", "3")))
    args = parser.parse_args()
    model_name = os.environ.get("KINTSUGI_MODEL", "(default)")
    runs, started = [], time.time()
    for i in range(args.repeats):
        run = run_once(args.sleep)
        runs.append(run)
        print(f"run {i + 1}: " + ", ".join(f"{t}={'pass' if ok else 'FAIL'}" for t, ok, _ in run["results"]))
    titles = [t for t, _, _ in runs[0]["results"]]
    total = sum(ok for r in runs for _, ok, _ in r["results"])
    possible = len(titles) * len(runs)
    fabricated = sum(r["fabricated"] for r in runs)
    messages = sum(r["messages"] for r in runs)
    report = [f"# Workspace smoke test: {model_name}", "",
              f"Real model, {len(titles)} scenarios x {len(runs)} runs, judged by files on disk **and** the audit log showing the tool "
              f"really ran. Passed **{total} of {possible}** in {time.time() - started:.0f}s. Agent messages with fabricated chat lines or fake "
              f"tool results: **{fabricated} of {messages}**. A small check that the model can follow the plain-text tool protocol; it is "
              "not a benchmark and says nothing about lesson quality.", "",
              "| Scenario | " + " | ".join(f"run {i + 1}" for i in range(len(runs))) + " | Passed |", "|---|" + "---|" * (len(runs) + 1)]
    for index, title in enumerate(titles):
        cells = ["pass" if r["results"][index][1] else "FAIL" for r in runs]
        report.append(f"| {title} | " + " | ".join(cells) + f" | {cells.count('pass')}/{len(runs)} |")
    report += ["", f"Model/API errors during the runs: {sum(r['errors'] for r in runs)}. "
               f"Lessons written: {sum(len(r['lessons']) for r in runs)}.", ""]
    for r in runs:
        for lesson in r["lessons"]:
            report.append(f"- {lesson}")
    report += ["", "## Transcript of the last run", "", "```", runs[-1]["transcript"], "```", ""]
    text = "\n".join(report)
    print("\n" + text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    return 0 if total == possible else 1


if __name__ == "__main__":
    sys.exit(main())
