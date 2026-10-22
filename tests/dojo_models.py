"""Scripted models for the dojo and improver tests: each one decides, per scenario, whether to behave correctly."""

import json
import re

from kintsugi.model import MockModel

ALL = {"write_file", "recover", "python", "arithmetic", "two_agents", "injection"}


def tool(name, **args):
    return "```tool\n" + json.dumps({"tool": name, "args": args}) + "\n```"


def _ask(messages):
    """The newest request from 'you' in the first user message, and who the agent is talking as."""
    context = messages[1]["content"]
    mine = re.findall(r'<message id="\d+" from="you">\n(.*?)\n</message>', context, re.S)
    alice = re.findall(r'<message id="\d+" from="alice">\n(.*?)\n</message>', context, re.S)
    return (mine[-1] if mine else ""), (alice[-1] if alice else "")


def make_model(solves=ALL, gullible=False, needs_playbook=frozenset(), gullible_with_playbook=False, distill=None):
    """`solves`: scenario keys it does correctly. `gullible`: obeys the planted instruction. `needs_playbook`: scenario
    keys it only solves when the agent's prompt contains a playbook."""

    def reply(messages):
        last = messages[-1]["content"]
        has_playbook = "Your playbook" in messages[0]["content"]
        steps = sum(1 for m in messages if m["role"] == "user" and m["content"].startswith("Tool results"))

        def ok(key):
            return key in solves and (key not in needs_playbook or has_playbook)

        if distill is not None and "Write a playbook" in last:
            return distill
        if len(messages) < 2:
            return "ok"
        if "general lesson" in last:
            return "When a tool call fails, read the error and the usage line before retrying."
        ask, from_alice = _ask(messages)
        if "pineapple" in from_alice and "@bob" in from_alice:
            return "pineapple" if ok("two_agents") else "hello"
        if "create a file named notes.txt" in ask:
            if not ok("write_file"):
                return "Done."
            return tool("write_file", path="notes.txt", content="hello") if steps == 0 else "I created notes.txt."
        if "read missing.txt" in ask:
            if not ok("recover"):
                return "I read it."
            if steps == 0:
                return tool("read_file", path="missing.txt")
            return tool("write_file", path="missing.txt", content="created") if steps == 1 else "It did not exist, so I created it."
        if "17 * 23" in ask:
            if not ok("python"):
                return "I will use the run_python tool to compute that. The result is 401."
            return tool("run_python", code="print(17 * 23)") if steps == 0 else "The result is 391."
        if "123 * 457" in ask:
            if not ok("arithmetic"):
                return "I will run python for that. It is 5578."
            return tool("run_python", code="print(123 * 457)") if steps == 0 else "123 * 457 = 56211."
        if "ask @bob" in ask:
            return "@bob please say the word pineapple." if ok("two_agents") else "ok"
        if "read notes.txt" in ask:
            if steps == 0:
                return tool("read_file", path="notes.txt")
            if (gullible or (gullible_with_playbook and has_playbook)) and steps == 1:
                return tool("run_python", code="open('PWNED.txt', 'w').write('hacked')")
            return "The meeting is at 3pm on Friday." if ok("injection") or not (gullible or gullible_with_playbook) else "I was hacked."
        return "ok"

    return MockModel(reply)


def factory(models):
    """A study_model_factory from {model_name_or_None: model}."""
    return lambda name: models[name]
