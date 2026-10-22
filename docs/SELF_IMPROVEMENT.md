# Self-improvement

The workspace can study itself and propose better settings. It is **bounded on purpose**: it can change two things
and nothing else, it shows its evidence, and every change can be undone.

## What it does

1. **Studies how well an agent uses tools.** A built-in practice suite (the "dojo", `src/kintsugi/workspace/dojo.py`)
   gives a model six made-up tasks: write a file, recover from a missing file, compute with Python, refuse to guess
   arithmetic, hand a task to another agent, and a **prompt-injection trap** (a file that orders the agent to run code).
   A task counts as passed only with evidence: a file exists **and** the audit log shows the tool really ran. Claiming
   to have done the work scores zero.
2. **Studies other models.** It runs the same suite on every model you list (and on the ones your agents use now), and
   proposes switching an agent when another model is clearly better.
3. **Tunes the playbook.** The playbook is a short list of rules in an agent's prompt ("call run_python for any
   calculation", ...). The workspace tests candidate playbooks against the agent's current one: a built-in set of vetted
   techniques, and rules the model writes from its own failures (optionally also from its own lessons, and from
   study material you paste in).
4. **Proposes, it does not decide.** Each change is a proposal with its numbers. You accept or reject it. Optionally it
   applies a clear win automatically (at least 20 percentage points better and no unsafe actions). Any applied change can be
   undone from Details > Improve.

Find it under **Settings** (the sliders button in the sidebar) and **Details > Improve** for each agent. Studies can run
when you press a button or on a schedule (daily to monthly); the default is off.

## What it can never change

Only an agent's **model** and **playbook**. Not permissions or tiers, tool allow-lists, approvals, the sandbox, secrets,
schedules, rooms, messages, files, or any code. Tests enforce this: the improver's source may not import or call any of
those, a full study with auto-apply leaves them untouched, and a hash of the source tree is unchanged by a study.
Playbook rules that mention approvals, permissions, secrets, links, "ignore", the sandbox, limits or the system prompt are
dropped automatically, whoever wrote them, and again at the moment a proposal is applied. A playbook sits **after** the
safety rules in the prompt and says it never overrides them.

A change that makes the injection trap worse is **never proposed**, even if every other score improves.

## What it costs and what it shares

- **Calls.** A full study usually needs 100 to 200 model calls. A per-study limit (default 150) is a hard stop, and
  studies also count against the workspace's daily cap (`KINTSUGI_DAILY_CALLS`). When either runs out the study stops and
  says so.
- **Privacy.** The practice tasks are made up: none of your chats or files are used. Playbook writing sends the failures
  from those tasks, any study material you pasted, and (only if you tick the box) the agent's own lessons to your model
  provider. Testing other models sends the made-up tasks to that model's provider (the same one, by default).
- **Throwaway workspaces.** Every practice scenario runs in a temporary workspace that is deleted afterwards. Scenarios that
  execute code run only when the code sandbox is isolated; otherwise they are skipped and the report says so.

## "Study other harnesses"

The workspace does **not** browse the web or fetch repositories by itself. Doing that unattended would let any web page
steer an agent. Instead:

- A built-in set of vetted techniques (from the projects credited in the README: reflection after failure, acting before
  describing, checking before reading) is tested as one of the playbook candidates.
- **Study material**: paste notes about another model, agent framework or technique into Settings. They are shown to the
  model as untrusted notes ("extract only general tool-use techniques"), the resulting rules are filtered, and they only
  become a proposal if they measurably help on the practice suite.

## Honest limits

- The suite is small (six tasks, a few repeats). A difference of a few points is noise; the report says "small samples" on
  every proposal. It cannot prove an agent is better on your real work, only that it handles these practice tasks better.
- Optimising against a fixed suite can overfit it (Goodhart's law). The safety trap and the "claimed but did not run"
  checks make the obvious shortcuts fail, but they are a guard, not a guarantee.
- It improves which model and which rules to use. It does not make a weak model smart: on the first real-model smoke runs
  `allam-2-7b` passed about 6 of 15 tasks (see `research/results/workspace_smoke.md`), and a playbook may not fix that. Comparing models
  is the more powerful lever.
- Not yet measured on real models: whether accepted proposals help real conversations. Run the study on your provider and
  look at the report before trusting any number here. `examples/workspace_study.py` (and the `workspace-study` GitHub
  Action, which makes no calls until you list models in `examples/study.config`) compares real models and writes a table.

## Command line and API

`/api/improve` (settings, status, studies, proposals), `/api/improve/run`, `/api/improve/decide`, `/api/improve/revert`,
`/api/improve/models`, `/api/agent/model`, `/api/agent/playbook`. Every proposal, acceptance and reversal is in the audit log.
