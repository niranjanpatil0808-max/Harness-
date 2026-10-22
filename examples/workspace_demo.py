"""Offline demo of the Kintsugi workspace. Uses scripted mock models, so it needs no API key.

    python examples/workspace_demo.py

It shows: a request answered with a tool, a failed tool call turned into a lesson, a risky tool waiting for
approval, a secret used but never leaked, two agents talking in a room, a cron job and a published web app.
"""

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kintsugi.memory import MemoryStore  # noqa: E402
from kintsugi.model import MockModel  # noqa: E402
from kintsugi.workspace import Workspace  # noqa: E402
from kintsugi.workspace.scheduler import Scheduler  # noqa: E402


def tool(_tool, **args):
    return "```tool\n" + json.dumps({"tool": _tool, "args": args}) + "\n```"


def scripted(replies):
    queue = list(replies)

    def reply(messages):
        if "general lesson" in messages[-1]["content"]:
            return "When a file may not exist, list the folder before reading it."
        return queue.pop(0) if len(queue) > 1 else queue[0]

    return MockModel(reply)


def show(ws, room, start=0):
    for m in ws.history(room, limit=100)[start:]:
        print(f"  {m['sender']:>8}: {m['text']}")
    return len(ws.history(room, limit=100))


with tempfile.TemporaryDirectory() as tmp:
    models = {}
    ws = Workspace(tmp, model_factory=lambda name: models[name], encrypt_keychain=False)
    ws.create_agent("alice", persona="You are a careful assistant.")
    ws.create_agent("bob", persona="You review work.")
    ws.create_room("team", ["alice", "bob", "you"])
    ws.keychain.set("alice", "DEMO_KEY", "sk-demo-super-secret-value")
    models["bob"] = scripted(["Reviewed: the plan looks fine."])
    pos = 0

    def script(*replies):  # what alice's (mock) model will say in the next scenario
        models["alice"] = ws._models["alice"] = scripted(replies)

    print("\n1. A request that first fails, then recovers (and writes a lesson)")
    script(tool("read_file", path="plan.txt"), tool("list_files"), tool("write_file", path="plan.txt", content="1. ship"),
           "I could not find plan.txt, so I created it.")
    ws.post("team", "you", "@alice read plan.txt for me")
    pos = show(ws, "team", pos)
    lessons = MemoryStore.load(ws.lessons_path("alice")).lessons
    print(f"  -> alice's lessons: {[l.text for l in lessons]}")

    print("\n2. A risky tool waits for approval; the secret is used but never shown")
    script(tool("run_python", code="import os; print('key length', len(os.environ['DEMO_KEY']))", secrets=["DEMO_KEY"]))
    ws.post("team", "you", "@alice check how long the demo key is")
    approval = ws.approvals()[0]
    print(f"  -> approval #{approval['id']}: {approval['tool']} {approval['args'][:60]}...")
    ws.decide(approval["id"], True)
    pos = show(ws, "team", pos)
    assert "sk-demo-super-secret-value" not in json.dumps(ws.history("team"))

    print("\n3. A web app published by an agent")
    script(tool("publish_app", name="hello", html="<h1>Hello from alice</h1>"))
    ws.post("team", "you", "@alice publish a hello app")
    ws.decide(ws.approvals()[0]["id"], True)
    pos = show(ws, "team", pos)
    print(f"  -> served at /apps/alice/hello/ ; file exists: {(ws.www_dir('alice') / 'hello' / 'index.html').exists()}")

    print("\n4. Two agents talking in a room")
    script("@bob please review plan.txt")
    ws.post("team", "you", "@alice ask bob to review the plan")
    pos = show(ws, "team", pos)

    print("\n5. A scheduled job")
    script(tool("schedule", cron="0 9 * * 1-5", prompt="post the daily standup"))
    ws.post("team", "you", "@alice schedule a weekday standup")
    ws.decide(ws.approvals()[0]["id"], True)
    script("Good morning, standup time!")
    Scheduler(ws).tick(datetime(2026, 10, 26, 9, 0, 3).timestamp())
    pos = show(ws, "team", pos)
    ws.close()
