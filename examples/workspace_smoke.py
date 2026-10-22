"""Smoke test of the workspace against a REAL model (needs KINTSUGI_API_KEY; model via KINTSUGI_MODEL).

    python examples/workspace_smoke.py [--out results/workspace_smoke.md]

Each scenario is judged by something that can be checked without trusting the model's words (a file on disk,
a number in the reply). It reports pass or fail for each, the number of model calls, and the transcript.
Agents run in the 'dangerous' tier so that run_python does not wait for a human. Small and cheap on purpose:
it shows whether a given model can follow the plain-text tool protocol at all. It is not a benchmark.
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kintsugi.model import OpenAIAdapter  # noqa: E402
from kintsugi.workspace import Workspace  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sleep", type=float, default=float(os.environ.get("SMOKE_SLEEP", "3")))
    args = parser.parse_args()
    model_name = os.environ.get("KINTSUGI_MODEL", "(default)")

    with tempfile.TemporaryDirectory() as tmp:
        models = {}
        ws = Workspace(tmp, model_factory=lambda n: models.setdefault(n, OpenAIAdapter()), encrypt_keychain=False)
        ws.create_agent("alice", persona="You are a careful assistant.", tier="dangerous")
        ws.create_agent("bob", persona="You review work and answer briefly.", tier="dangerous")
        ws.create_room("team", ["alice", "bob", "you"])
        files = ws.files_dir("alice")

        def last_reply(room="team", sender="alice"):
            return next((m["text"] for m in reversed(ws.history(room, limit=200)) if m["sender"] == sender), "")

        scenarios = [
            ("write a file", "@alice create a file named notes.txt that contains the word hello",
             lambda: (files / "notes.txt").is_file() and "hello" in (files / "notes.txt").read_text().lower()),
            ("recover from a missing file", "@alice read missing.txt. If it does not exist, create it containing the text created.",
             lambda: (files / "missing.txt").is_file() and "created" in (files / "missing.txt").read_text().lower()),
            ("use python", "@alice use python to compute 17 * 23 and tell me the result.",
             lambda: "391" in last_reply()),
            ("two agents", "@alice ask @bob to say the word pineapple.",
             lambda: "pineapple" in last_reply(sender="bob").lower()),
        ]
        rows, started = [], time.time()
        for title, prompt, check in scenarios:
            before = sum(m.usage.calls for m in models.values())
            ws.post("team", "you", prompt, human=True)
            calls = sum(m.usage.calls for m in models.values()) - before
            try:
                ok = bool(check())
            except OSError:
                ok = False
            rows.append((title, ok, calls))
            print(f"{'PASS' if ok else 'FAIL'}  {title}  ({calls} model calls)")
            time.sleep(args.sleep)

        lessons = []
        from kintsugi.memory import MemoryStore

        lessons = MemoryStore.load(ws.lessons_path("alice")).lessons
        transcript = "\n".join(f"{m['sender']:>8}: {' '.join(m['text'].split())[:300]}" for m in ws.history("team", limit=500))
        errors = [r for r in ws.audit_log(500) if r["event"] == "run-error"]
        passed = sum(1 for _, ok, _ in rows if ok)
        report = [f"# Workspace smoke test: {model_name}", "",
                  f"Real model, {len(rows)} scenarios, judged by files on disk or numbers in the reply. "
                  f"Passed **{passed} of {len(rows)}** in {time.time() - started:.0f}s. A tiny check that the model can follow the "
                  "plain-text tool protocol; it is not a benchmark and says nothing about lesson quality.", "",
                  "| Scenario | Result | Model calls |", "|---|---|---|",
                  *[f"| {t} | {'pass' if ok else 'FAIL'} | {c} |" for t, ok, c in rows], "",
                  f"Model/API errors during the run: {len(errors)}. Lessons alice wrote: {len(lessons)}."]
        for lesson in lessons:
            report.append(f"- {lesson.text}")
        report += ["", "## Transcript", "", "```", transcript, "```", ""]
        text = "\n".join(report)
        print("\n" + text)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text)
        ws.close()
        return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
