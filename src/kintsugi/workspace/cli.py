"""`kintsugi workspace ...` commands. The workspace folder defaults to ./workspace (or $KINTSUGI_WORKSPACE)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from kintsugi.model import MockModel

from .core import Workspace, WorkspaceError


def _open(args: argparse.Namespace) -> Workspace:
    factory = (lambda name: MockModel(["(mock model: I cannot really answer)"])) if args.mock else None
    # the server must not run agents inside its request threads, so it uses a worker pool
    if args.wcmd == "serve" or (args.wcmd == "backup" and args.action == "restore"):
        from . import backup

        args.restored = backup.restore_if_empty(Path(args.dir))  # a free host that wiped its disk gets the encrypted backup back
    return Workspace(args.dir, model_factory=factory, sync=args.wcmd != "serve")


def seed(ws: Workspace) -> bool:
    """A starter team so the first run is not an empty screen. Does nothing if agents already exist."""
    if ws.list_agents():
        return False
    ws.create_agent("alice", persona="You are a friendly, careful general assistant.")
    ws.create_agent("bob", persona="You review work and point out mistakes politely.")
    ws.create_room("team", ["alice", "bob", "you"])
    ws.post_system("team", "Welcome! Try: @alice write a short todo list into todo.txt   (risky tools wait for your approval)")
    return True


def add_parser(sub) -> None:
    ws = sub.add_parser("workspace", help="agents with files, memory, rooms, permissions and schedules")
    ws.add_argument("--dir", type=Path, default=Path(os.environ.get("KINTSUGI_WORKSPACE", "workspace")))
    ws.add_argument("--mock", action="store_true", help="offline mock model (answers are canned)")
    cmds = ws.add_subparsers(dest="wcmd", required=True)

    cmds.add_parser("init", help="create the workspace folder with a starter team (alice, bob, room 'team')")
    serve = cmds.add_parser("serve", help="start the web UI and API")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    serve.add_argument("--host", default=os.environ.get("KINTSUGI_HOST", "127.0.0.1"))

    agent = cmds.add_parser("agent", help="add an agent")
    agent.add_argument("name")
    agent.add_argument("--persona", default="")
    agent.add_argument("--tier", default="auto", choices=["strict", "auto", "dangerous"])

    room = cmds.add_parser("room", help="add a room")
    room.add_argument("name")
    room.add_argument("members", nargs="*")

    say = cmds.add_parser("say", help="post a message as yourself")
    say.add_argument("room")
    say.add_argument("text")
    say.add_argument("--as", dest="sender", default="you")

    log = cmds.add_parser("log", help="show a room's messages")
    log.add_argument("room")

    backup = cmds.add_parser("backup", help="encrypted backup to your private GitHub repository (see docs/HOSTING.md)")
    backup.add_argument("action", choices=["now", "status", "restore"], nargs="?", default="status")

    cmds.add_parser("approvals", help="list tool calls waiting for approval")
    approve = cmds.add_parser("approve", help="approve a waiting tool call")
    approve.add_argument("id", type=int)
    deny = cmds.add_parser("deny", help="deny a waiting tool call")
    deny.add_argument("id", type=int)

    tier = cmds.add_parser("tier", help="change an agent's permission tier")
    tier.add_argument("agent")
    tier.add_argument("tier", choices=["strict", "auto", "dangerous"])

    job = cmds.add_parser("job", help="schedule an agent: job AGENT ROOM 'CRON' 'PROMPT'")
    job.add_argument("agent")
    job.add_argument("room")
    job.add_argument("cron")
    job.add_argument("prompt")

    secret = cmds.add_parser("secret", help="store a secret for an agent (the value is asked for, never echoed)")
    secret.add_argument("agent")
    secret.add_argument("name")

    delete = cmds.add_parser("delete-agent", help="delete an agent and everything it owns (files, memory, secrets, chats)")
    delete.add_argument("name")
    delete_room = cmds.add_parser("delete-room", help="delete a room and its messages")
    delete_room.add_argument("name")
    purge = cmds.add_parser("purge", help="delete messages and audit entries older than N days")
    purge.add_argument("days", type=float)
    cmds.add_parser("status", help="show how code is isolated, where data goes, and today's model-call usage")
    cmds.add_parser("audit", help="show the audit trail")
    ws.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    ws = _open(args)
    try:
        cmd = args.wcmd
        if cmd == "init":
            print(f"workspace ready in {args.dir}" + (" with agents alice and bob in room 'team'" if seed(ws) else ""))
        elif cmd == "serve":
            from .server import serve

            if seed(ws):
                print("Empty workspace: created the starter team (alice, bob, room 'team').")
            serve(ws, args.host, args.port)
            return 0
        elif cmd == "agent":
            ws.create_agent(args.name, args.persona, args.tier)
            print(f"agent {args.name} created ({args.tier})")
        elif cmd == "room":
            ws.create_room(args.name, args.members)
            print(f"room {args.name} created")
        elif cmd == "say":
            ws.post(args.room, args.sender, args.text, human=True)
            for m in ws.history(args.room, limit=10):
                print(f"{m['sender']}: {m['text']}")
        elif cmd == "log":
            for m in ws.history(args.room, limit=50):
                print(f"[{m['id']}] {m['sender']}: {m['text']}")
        elif cmd == "backup":
            from . import backup

            if args.action == "restore":
                if not args.restored:
                    print("Nothing restored (the workspace already has data, or no backup is available).")
                    return 1
            elif args.action == "now":
                result = ws.backups.run(force=True)
                print("Backed up." if result["ok"] else f"Backup failed: {result['error']}")
                return 0 if result["ok"] else 1
            else:
                print(json.dumps(ws.backups.status(), indent=2))
        elif cmd == "approvals":
            rows = ws.approvals()
            for a in rows:
                print(f"#{a['id']} {a['agent']} wants {a['tool']} {a['args'][:120]}")
            if not rows:
                print("nothing waiting")
        elif cmd in ("approve", "deny"):
            print(ws.decide(args.id, cmd == "approve", by="cli"))
        elif cmd == "tier":
            ws.set_tier(args.agent, args.tier)
            print(f"{args.agent} is now '{args.tier}'")
        elif cmd == "job":
            print(f"job {ws.add_job(args.agent, args.room, args.cron, args.prompt)} scheduled")
        elif cmd == "secret":
            ws.get_agent(args.agent)
            ws.keychain.set(args.agent, args.name, getpass.getpass(f"value for {args.name}: "))
            print(f"stored {args.name} for {args.agent}")
        elif cmd == "delete-agent":
            ws.delete_agent(args.name)
            print(f"deleted agent {args.name} and everything it owned")
        elif cmd == "delete-room":
            ws.delete_room(args.name)
            print(f"deleted room {args.name}")
        elif cmd == "purge":
            print(f"deleted {ws.purge_messages(args.days)} messages older than {args.days:g} days")
        elif cmd == "status":
            from . import sandbox

            info = sandbox.status()
            print(f"code sandbox : {info['backend']} ({info['note']})")
            print(f"network      : {'blocked for agent code' if info['network_blocked'] else 'NOT blocked for agent code'}")
            print(f"data goes to : {ws.provider()} (conversation text is sent there whenever an agent thinks)")
            print(f"model calls  : {ws.calls_today()} today, limit {ws.daily_calls or 'none'}")
            print(f"data folder  : {ws.root}")
        elif cmd == "audit":
            for row in ws.audit_log(50):
                print(f"{row['agent'] or '-':10} {row['event']:20} {row['detail']}")
        return 0
    except (WorkspaceError, ValueError) as err:
        print(f"error: {err}")
        return 1
    finally:
        if args.wcmd != "serve":
            ws.close()
