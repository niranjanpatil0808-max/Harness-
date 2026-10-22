# Kintsugi (working name)

**A phone-first assistant you can trust with real work.** AI agents that remember, work on a schedule, ask before they do anything risky, run your code in a locked box, and only change themselves when a measurement says it helps.

> Built for the Meta Global AI Developer Hackathon (Indie developer track). Python standard library only (plus two small web libraries bundled for the interface).
> The name is a placeholder and will change.

## Where things stand

| | Status |
|---|---|
| Chat interface (rooms, direct messages, light and dark, phone layout), agents with their own files, notes, secrets, schedules and web apps | **Works today** |
| Approvals that show the full code, isolated code sandbox, daily spending cap, delete/export your data | **Works today** ([SECURITY.md](SECURITY.md)) |
| Mistake memory: a failed tool call becomes a lesson the agent remembers | **Works, but its benefit is not measured** |
| Self-improvement: tests models and playbooks, proposes changes you review and can undo | **Works** ([docs/SELF_IMPROVEMENT.md](docs/SELF_IMPROVEMENT.md)); not yet run against real models |
| Hosting recipes (Codespaces, Render, Docker) | **Written and checked locally**; not yet deployed |
| **Phone app:** installable, works offline as a shell, thumb-friendly, edge-swipe sidebar | **Works** ([docs/PHONE.md](docs/PHONE.md)); tested in a phone-sized browser, not yet on real devices |
| **Voice:** speak and hear replies with your browser's free speech, optional hands-free loop | **Works** in tests with faked speech engines; quality on real phones varies (iPhone is patchier) |
| **A tone you choose** (Fun, Regular, Brief, Custom), per person | **Works**; style only, never the rules |
| **Web search** with your own key (Tavily or Brave): cited snippets, no page fetching | **Works** against test servers; **not yet tried against the live services** |
| **Automations:** daily briefing, change watcher that stays silent unless something matters, research report, your own task; your time zone | **Works** (scheduling and time zones tested incl. daylight saving); search-based ones need a search key |
| **Notifications** that never contain your message, plus unread markers and an app badge | **Works** in tests with a fake push service; **not yet verified against Google's, Apple's or Mozilla's real push services** |
| **Encrypted backup** to your private GitHub repo, restored automatically on an empty free host | **Works** against a fake GitHub in tests; **not yet tried against the real GitHub** ([docs/HOSTING.md](docs/HOSTING.md)) |
| Teams: separate logins, invite links, roles for approvals, shared rooms plus private chats | **Planned, after Oct 25** |
| Integrations: GitHub, then Slack, then Gmail and Calendar | **Planned, after teams** |

Rows marked planned do not exist yet. This table is updated as each one lands, and it says what has and has not been verified.

## What it is for

Today it is best for **one person** (a founder, a builder) who wants a few agents they can actually trust: they cannot run harmful code without your approval, they cannot see your other files or the network when they run code, they cannot overspend your model quota, and everything they know and do can be seen and deleted. Startup **teams** are the goal; the features that make it matter for a team (accounts, roles, integrations) are not built yet, and I would not pitch it to a team today.

## Quick start

```bash
git clone https://github.com/niranjanpatil0808-max/KINTSUGI.git && cd KINTSUGI
pip install -e .
python -m unittest discover -s tests         # 250+ offline tests
python examples/workspace_demo.py            # an offline tour, no key needed (a recording: docs/demo.html)

export GROQ_API_KEY=...                      # or KINTSUGI_API_KEY / KINTSUGI_BASE_URL / KINTSUGI_MODEL
kintsugi workspace serve                     # creates a starter team and prints a link with your access token
```

Open the link on your computer or phone. Any OpenAI-compatible endpoint works (Groq by default; a Llama endpoint, Together, Fireworks or a local Ollama server by setting `KINTSUGI_BASE_URL` and `KINTSUGI_MODEL`).

**On a phone with no computer:** open the repository in a GitHub Codespace (Code > Codespaces), or deploy it with the recipes in [docs/HOSTING.md](docs/HOSTING.md). Add your key as a secret, never in a chat or in the repository.

## How it keeps you safe

- **Approvals.** Risky tools (running code, publishing an app, scheduling) wait for you. The card shows the whole code and says whether it will run isolated.
- **Isolation.** On Linux, approved code sees only its own agent's folder: no other files, no keys, no network. Where that is blocked it falls back to a separate unprivileged user, and if nothing works the app says **"not isolated"**.
- **Cost guard.** A daily limit on model calls protects your free quota from a runaway loop.
- **Privacy.** Your conversation text goes to your model provider and nothing else leaves your server. Secrets are write-only. You can download or delete everything.
- **Honest limits** are listed in [SECURITY.md](SECURITY.md): it is not a hardened container, has no accounts yet, and has not been audited.

## How it learns, and how it improves itself

- **Lessons.** When an agent's tool call fails, the model writes one short general lesson. Lessons are shown on later tasks, kept when they help and dropped when they do not.
- **Self-improvement.** A built-in practice suite (including a trap file that orders the agent to run code) tests your agents and other models. It proposes a better model or playbook **only** when it measurably wins and is no less safe. You review each change and can undo it. It can change nothing else: not permissions, secrets, the sandbox or code. Off by default. [Details and limits](docs/SELF_IMPROVEMENT.md).

## Honest limitations

- **Real-model reliability is unproven.** On the first real runs a tiny model (`allam-2-7b`) completed 6 of 15 practice tasks, and made up answers rather than running tools until safeguards were added. Better models should do better, but that has not been measured. No Meta model has been tested yet.
- **The benefit of lessons and self-improvement is not measured** on real conversations. Tests show the mechanisms work, not that they make an agent better.
- **Free hosting loses data** when the service restarts unless you turn on the encrypted backup (needs a private GitHub repo and a passphrase you must not lose).
- **One shared access token, no accounts, no TLS of its own** (hosting platforms provide it).
- **The practice suite is small.** A difference of a few points is noise.
- Everything the measured research showed, and did not show, is in [research/README.md](research/README.md).

## Research: the harness for weak models

The repository started as an experiment: can a small open model fix more bugs if it retries against tests, learns from its mistakes and sees only the relevant code? The honest answer so far is "a little": retrying repaired 2 of 21 held-out tasks on one model, and memory and the context graph showed no measurable effect. That work is kept as research, and parts of it (memory, the code verifier, the context graph, the model adapter) power the product. See [research/README.md](research/README.md) and [RESULTS.md](RESULTS.md).

## Credits and inspirations

Ideas only; all code here is written from scratch. Licenses were checked on each repository page on 2026-10-21 (QM and the bundled libraries on 2026-10-22).

| Project | License | Idea taken | Where it lives here |
|---|---|---|---|
| [yc-software/qm](https://github.com/yc-software/qm) | MIT | A workspace where agents have durable memory, files and a sandbox, talk in channels, and run under tiered permissions with a keychain and scheduled jobs | `src/kintsugi/workspace/`: a small reimplementation (no Slack, Postgres or cloud yet); the mistake memory and self-improvement are additions |
| [markedjs/marked](https://github.com/markedjs/marked) and [cure53/DOMPurify](https://github.com/cure53/DOMPurify) | MIT; Apache-2.0 or MPL-2.0 | Ready-made components used as they are (not reimplemented) | `src/kintsugi/workspace/web/vendor/` renders and sanitises agent replies; licenses are included next to the files |
| [google-research/harness2](https://github.com/google-research/harness2) | Apache-2.0 | Improve the harness around a frozen model; keep a change only when it measurably wins, and carry lessons forward | Lessons are promoted only after a task that used them passed; self-improvement proposals need evidence |
| [noahshinn/reflexion](https://github.com/noahshinn/reflexion) | MIT | Verbal self-reflection after a failure, fed into the next attempt | The "write one general lesson" step |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | MIT | A tiny agent loop that skips the tool-calling API, so any model works | Agents call tools by writing a fenced JSON block in plain text |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) (repo map) | Apache-2.0 | A map of definitions and references ranked with PageRank | `graph.py`: stdlib PageRank over the `ast` graph (used by the `map_project` tool and the research harness) |
| [ReflexioAI/reflexio](https://github.com/ReflexioAI/reflexio) | Apache-2.0 | Turn repeated corrections into lasting, deduplicated behavior changes | Near-duplicate lessons merge and count how often they recur |
| [PrimeIntellect-ai/prime-agent](https://github.com/PrimeIntellect-ai/prime-agent) | MIT | Harness state (prompts, memories) kept as durable files, updated in small evidence-backed steps | `lessons.json` and playbooks are plain data; every change records its evidence |
| Grok (xAI), as a product reference | not code | A witty-but-useful assistant with live web search, voice and a phone app | Inspiration for the planned tone choice, web search and voice; no Grok code or assets are used |

## Project layout

```
src/kintsugi/workspace/   the product: core.py agents.py tools.py perms.py sandbox.py keychain.py scheduler.py backup.py
                          server.py db.py dojo.py improve.py cli.py  web/ (the interface)
src/kintsugi/             engine modules the product reuses: model.py memory.py graph.py loop.py verifier.py
SECURITY.md  Dockerfile  render.yaml  .devcontainer/  docs/ (PHONE, WORKSPACE, HOSTING, SELF_IMPROVEMENT, demo.html)
examples/                 workspace_demo.py, smoke and model-comparison scripts
tests/                    offline tests (python -m unittest discover -s tests) and tests/ui (browser tests)
research/                 the original weak-model experiment (write-up); benchmark/, results/ and RESULTS.md move here soon
```

Tests use the standard library's `unittest`, so a fresh clone needs no installs to run them.

## License

MIT, see [LICENSE](LICENSE).
