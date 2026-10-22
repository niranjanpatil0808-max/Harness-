# Kintsugi Workspace

A small, local, standard-library-only workspace where AI agents live: each agent has its own files, notes,
secrets, permissions, schedule and web apps, and they talk to you and to each other in rooms. What sets it
apart: **every agent keeps a mistake memory.** When one of its tool calls fails, the agent's model writes a
short general lesson; that lesson is shown on the retry and in later runs, kept when runs that used it
succeed, and dropped when it never helps. It is the same memory code ([`memory.py`](../src/kintsugi/memory.py))
that the bug-fix benchmark measures.

It is a small reimplementation of ideas from [QM](https://github.com/yc-software/qm) (MIT; see Credits). It is
not a port and not a clone: no Slack, no Postgres, no cloud deploy, roughly 2k lines of Python.

## Honest status

- The workspace is **tested** (see `tests/test_workspace_*.py`) and runs offline on a mock model. Whether real models can follow its plain-text tool protocol is checked by `examples/workspace_smoke.py` (run by the `workspace-smoke` GitHub Action; the report lands in `results/workspace_smoke.md`). Until that report exists, nothing here has been seen working with a real model.
- Whether agent lessons **improve** agent behaviour is **not measured**. The only measured result in this repo
  is on the bug-fix benchmark (see [RESULTS.md](../RESULTS.md)), where the retry loop helped a little and
  memory and the graph showed no measurable effect yet. Do not read the workspace as evidence for memory.
- The sandbox is **not a security sandbox** (below).

## Quick start

```bash
pip install -e .
python examples/workspace_demo.py            # offline tour, no key needed; docs/demo.html is a recording of it

export GROQ_API_KEY=...                      # or KINTSUGI_API_KEY / KINTSUGI_BASE_URL / KINTSUGI_MODEL
kintsugi workspace serve                     # starter team: agents alice and bob, room "team"
```

`serve` prints a link like `http://127.0.0.1:8765/#token=...`. Open it: you can chat, create agents and rooms,
approve or deny risky tool calls (the full code is shown before you approve), see each agent's lessons, files,
web apps and scheduled jobs, change an agent's permission tier, and open a direct message.

The same things from the command line:

```bash
kintsugi workspace init                      # create the folder and the starter team (also done by serve)
kintsugi workspace say team "@alice write a todo list into todo.txt"
kintsugi workspace approvals                 # risky tools wait here
kintsugi workspace approve 1                 # the tool runs, then the agent continues with the result
kintsugi workspace secret alice API_TOKEN    # asks for the value without echoing it
kintsugi workspace job alice team "0 9 * * 1-5" "post the daily standup"
```

(`kintsugi workspace --mock ...` uses a canned model, for trying the plumbing offline.)

### From a phone: GitHub Codespaces

Open the repository on GitHub, choose Code > Codespaces > Create. `.devcontainer/devcontainer.json` installs the
package, runs the tests and starts the server; the forwarded port opens in your browser. Before creating it, add
Codespaces secrets (GitHub > Settings > Codespaces > Secrets): `KINTSUGI_API_KEY` (your model key) and
`KINTSUGI_TOKEN` (any long random string: it becomes the access token you type into the page, or put it in
the URL as `#token=...`). Without `KINTSUGI_TOKEN`, run `cat workspace/token` in the Codespace terminal.
Never paste keys into a chat or an issue.

Times in cron schedules use the **server's** clock and time zone (a Codespace is usually UTC).

## Concepts

| Piece | What it is |
|---|---|
| **Agent** | A name, a persona, a permission tier, and a folder: `files/` (its sandbox), `www/` (its web apps), `lessons.json` (its mistake memory). |
| **Room / DM** | Durable message history in SQLite. A message wakes an agent when it is `@mentioned`, or for any message in a direct-message room. |
| **Loop guard** | Agent replies carry a hop count; after 4 agent-to-agent replies in a row the thread goes quiet. Each agent is also limited to 20 runs a minute. |
| **Tools** | Plain-text protocol: the model writes a fenced `tool` block of JSON, so any chat model works. Safe tools: `send_message`, `read_file`, `list_files`, `write_file`, `remember`, `search_memory`, `list_secrets`, `map_project`. Risky tools: `run_python`, `publish_app`, `fix_code`, `schedule`. |
| **Permission tiers** | `strict`: every tool waits for approval. `auto` (default): safe tools run, risky ones wait. `dangerous`: everything runs. An agent can also be limited to a list of tools. |
| **Approvals** | A waiting call is stored; a person approves or denies it from the CLI, API or web page. The run stops while it waits; after the decision the tool runs (if approved) and the agent is woken with the result, so it can finish the task. |
| **Keychain** | Secrets per agent, stored outside the prompt. A tool asks for a secret by name and it is injected as an environment variable into that one subprocess; the value is redacted from output. |
| **Scheduler** | 5-field cron (`*`, lists, ranges, steps). A due job posts `@agent prompt` into its room once per minute. At most 10 jobs per agent. |
| **Web apps** | `publish_app` writes `www/<name>/index.html`; the server serves it at `/apps/<agent>/<name>/` behind the access token, with a `sandbox` Content-Security-Policy so the app cannot call the API. |
| **Memory** | Two kinds: notes (`remember` / `search_memory`, keyword search) and lessons (written automatically from failed tool calls, via `MemoryStore.reflect`). |
| **`fix_code`** | An agent can call the Kintsugi loop itself on a folder with `task.json` and tests. |

## What the permission and sandbox layers do, and do not do

Done and tested: file tools cannot leave the agent's folder (absolute paths, `..`, `~`, backslashes, NUL
bytes and symlinks are refused); a folder is capped at 5 MB; `run_python` runs in a separate process with a
scrubbed environment, a wall-clock timeout, CPU and memory limits (POSIX `rlimit`), and its process group is
killed on timeout; API keys of the harness are not passed to it; secrets are redacted from tool output;
people cannot post under an agent's name; the API needs the access token and binds to 127.0.0.1.

**Not done:** `run_python` runs with your user's permissions. It can read files outside the agent's folder,
use the network and run other programs. Do not approve code you would not run yourself, and do not run the
workspace on a machine with secrets you cannot lose. A real sandbox needs a container or VM.
Without the optional `cryptography` package the keychain is a mode-600 file, **not encrypted**; with it, values
are encrypted with a key stored next to them (which protects against casual reading, not against someone
with access to the folder). The web page and API have no user accounts, only one shared token.

## HTTP API (all calls need header `X-Token`)

`GET /api/state`, `GET /api/messages?room=&after=`, `GET /api/lessons?agent=`, `GET /api/files?agent=`,
`GET /api/audit`, `POST /api/say {room,text}`, `/api/agents`, `/api/rooms`, `/api/dm`, `/api/tier`,
`/api/approve {id,approve}`, `/api/jobs`, `/api/jobs/delete`. Secrets can only be set from the CLI so that
they never travel through a chat message.

## Credits

Ideas from [yc-software/qm](https://github.com/yc-software/qm) (MIT, checked 2026-10-22): per-agent durable
memory, files and sandbox, channels and group messages, tiered permissions, a keychain, scheduled jobs.
All code here is written from scratch; nothing was copied.
