<h1 align="center">Kintsugi</h1>
<p align="center"><b>Work with your team and AI agents, together, in one shared space.</b><br>Self-hosted, phone-first, on your own API key.</p>

<p align="center">
  <a href="https://github.com/niranjanpatil0808-max/KINTSUGI/actions/workflows/ci.yml"><img alt="tests" src="https://github.com/niranjanpatil0808-max/KINTSUGI/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="license: MIT" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="runtime dependencies: none" src="https://img.shields.io/badge/runtime%20dependencies-none-brightgreen">
  <img alt="bring your own key" src="https://img.shields.io/badge/AI%20provider-bring%20your%20own%20key-orange">
</p>

<p align="center">
  <img src="docs/img/chat-approval.png" alt="A chat in Kintsugi: the agent asks to run code and the approval card shows exactly what will run" width="78%">
  <img src="docs/img/phone-chat.png" alt="The same workspace on a phone" width="17%">
</p>
<p align="center"><sub>Screenshots use the built-in scripted demo model, so they show the app, not a real model's answers.</sub></p>

Kintsugi is a shared workspace where **you, your teammates and AI agents work side by side**. Invite your team with a link, and everyone gets their own login, private chats and shared rooms. Hand an agent a task and the whole room follows it to done. Share a good answer with the team in one tap. Agents remember, work in parallel and on a schedule, and **learn how each person likes to work**.

You stay in control: agents ask before anything risky, run code in a locked box, go online only if you allow it, and show what they cost. You paste your own key (OpenAI, Anthropic, Gemini, DeepSeek, Groq, OpenRouter, Ollama or any OpenAI-style address). Nothing is hosted or sold for you, and your data stays on your server.

> Built for the Meta Global AI Developer Hackathon (Indie developer track). Python standard library only; two small web libraries are bundled for the interface. "Kintsugi" is a working name.

## Why it is different

| | |
|---|---|
| **Built for teams** | Invite teammates with single-use links and roles (owner, admin, member). Shared rooms, private chats, a **task board** (give an agent a job, everyone follows it to done), **Share** an answer into a room, @mentions, and approvals decided by the people you choose. |
| **Agents as teammates** | Several agents work at once, `@all` gives everyone the same task, and each agent keeps its own files, memory and schedule. |
| **Gets to know you** | Each agent learns every person's reply style and work context over time (👍/👎 and their own messages). You can see, edit, clear or switch it off. Work context stays in private chats. |
| **Safe by default** | Risky actions wait for approval and show the full code. Approved code runs with no network and sees only its own folder. A daily call limit protects your quota. |
| **Your key, your cost** | Any provider, one place to switch. A usage page shows calls, tokens and an estimated cost from prices you enter. |
| **Internet is a switch** | Each agent is Off, Ask each time, or Allow. Plugins add skills and web tools, previewed in full before install. |
| **Phone first** | Installable app, works as an offline shell, voice in and out, push notifications that never contain your message. |

<p align="center">
  <img src="docs/img/team-tasks.png" alt="The team task board" width="48%">
  <img src="docs/img/settings-usage.png" alt="The usage dashboard" width="48%">
</p>

## Quick start

```bash
git clone https://github.com/niranjanpatil0808-max/KINTSUGI.git && cd KINTSUGI
pip install -e .
kintsugi workspace serve        # prints a link with your access token
```

Open the link on your computer or phone. A short setup asks for your provider and **your own API key**, tests it, and offers a starter team. Keys are stored in your keychain, never shown again, and only sent to that provider. No computer? Open the repository in a GitHub Codespace, or follow [docs/HOSTING.md](docs/HOSTING.md) (Render, Docker). Try it offline first: `python examples/workspace_demo.py`.

## Read more

[Teams](docs/TEAMS.md) · [Security and its limits](SECURITY.md) · [Phone](docs/PHONE.md) · [Plugins](docs/PLUGINS.md) · [Integrations](docs/INTEGRATIONS.md) · [Hosting](docs/HOSTING.md) · [Self-improvement](docs/SELF_IMPROVEMENT.md) · [Contributing](CONTRIBUTING.md)

## What works, and what has been verified

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
| **Bring your own key:** any OpenAI-style API (OpenAI, DeepSeek, Groq, Together, OpenRouter, Ollama...), Anthropic or Gemini; set up in the app, per agent if you like | **Works** against fake servers in tests; **not yet tried with real keys** (I have none of those services here) |
| **Internet control:** each agent is Off / Ask each time / Allow, plus a master switch; agents can read one public page as text | **Works** in tests (including attempts to reach private addresses); not yet tried on the live internet |
| **Agents in parallel:** several agents work at once; `@all` gives everyone the same task; you set how many | **Works** (tested for real overlap) |
| **Plugins:** skills and web-API tools from a folder or GitHub repo, previewed in full before install ([docs/PLUGINS.md](docs/PLUGINS.md)) | **Works** against fake servers; no plugin code runs; Python-code plugins are **not built** |
| **Encrypted backup** to your private GitHub repo, restored automatically on an empty free host | **Works** against a fake GitHub in tests; **not yet tried against the real GitHub** ([docs/HOSTING.md](docs/HOSTING.md)) |
| **Teams:** separate logins through single-use invite links, owner/admin/member roles, who may approve, shared rooms plus private chats ([docs/TEAMS.md](docs/TEAMS.md)) | **Works** (permission matrix tests and a two-browser test); not yet used by a real group over a real deployment |
| **Integrations:** GitHub (read-only, repo allow-list), Slack (read; posting is off by default and always asks), Calendar (read-only secret iCal address), Gmail (read-only IMAP) — no app registration ([docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)) | **Works** against local fakes; **not yet tried against the real GitHub, Slack, Google Calendar or Gmail** |
| **Easier to use:** first-run setup (pick a provider, test your key, pick a starter team), a Settings page with sections, Ctrl/Cmd+K search across chats, agents, settings and messages, Stop button, Copy / Ask again, attach text files, save a chat as Markdown | **Works** in browser tests (desktop and phone size) |
| **Usage dashboard:** calls per day, per agent and per model; tokens when your provider reports them; a cost estimate from prices you enter | **Works**; the estimate is only as good as the prices you type, your provider's bill is the final word |
| **Long chats:** agents see the last 12 messages plus a short running summary of older ones (one extra model call per 16 older messages; owner can switch it off) | **Works** in tests with scripted models; summary quality depends on your model |
| **Team work with agents:** a shared task board (give an agent a task in a room, everyone follows it to done, with approvals shown), Share a message into another room, @person mentions, files given in a chat stay in that chat ([docs/TEAMS.md](docs/TEAMS.md)) | **Works** in unit and browser tests (desktop and phone); not yet used by a real team |
| **Gets to know you:** agents learn each person's preferred reply style and work context over time from their messages and 👍/👎, per person; you can see, edit, clear or switch it off (work context only in private chats) | **Works** in tests with scripted models; how well it learns depends on your model |

Rows marked planned do not exist yet. This table is updated as each one lands, and it says what has and has not been verified.

## What it is for

It works for **one person** (a founder, a builder) who wants a few agents they can actually trust, and for a **small team**: the owner invites teammates with single-use links, gives them a role, and they get their own logins, private chats and shared rooms. Agents cannot run harmful code without approval, cannot see your other files or the network when they run code, cannot overspend your model quota, and everything they know and do can be seen and deleted. What a team still lacks: single sign-on, a fully separate memory per person (files an agent writes and its lessons from mistakes are shared; chat notes, uploads and summaries are kept per chat), and integrations beyond GitHub, Slack, Calendar and Gmail.

## How it keeps you safe

- **Approvals.** Risky tools (running code, publishing an app, scheduling) wait for you. The card shows the whole code and says whether it will run isolated.
- **Isolation.** On Linux, approved code sees only its own agent's folder: no other files, no keys, no network. Where that is blocked it falls back to a separate unprivileged user, and if nothing works the app says **"not isolated"**.
- **Cost guard.** A daily limit on model calls protects your free quota from a runaway loop.
- **Privacy.** Your conversation text goes to your model provider and nothing else leaves your server. Secrets are write-only. You can download or delete everything.
- **Honest limits** are listed in [SECURITY.md](SECURITY.md): it is not a hardened container, has no email check or single sign-on for teammates, and has not been audited.

## How it learns, and how it improves itself

- **Lessons.** When an agent's tool call fails, the model writes one short general lesson. Lessons are shown on later tasks, kept when they help and dropped when they do not.
- **Self-improvement.** A built-in practice suite (including a trap file that orders the agent to run code) tests your agents and other models. It proposes a better model or playbook **only** when it measurably wins and is no less safe. You review each change and can undo it. It can change nothing else: not permissions, secrets, the sandbox or code. Off by default. [Details and limits](docs/SELF_IMPROVEMENT.md).

## Honest limitations

- **Nothing has been tried at scale with real services yet.** Providers, push services, GitHub, Slack, Google and real phones were tested only against fakes and a phone-sized browser, and no real team has used it. Treat it as a strong beta.
- **Real-model reliability is unproven.** On the first real runs a tiny model (`allam-2-7b`) completed 6 of 15 practice tasks, and made up answers rather than running tools until safeguards were added. Better models should do better, but that has not been measured. No Meta model has been tested yet.
- **The benefit of lessons and self-improvement is not measured** on real conversations. Tests show the mechanisms work, not that they make an agent better.
- **Free hosting loses data** when the service restarts unless you turn on the encrypted backup (needs a private GitHub repo and a passphrase you must not lose).
- **The owner token is one shared secret; no TLS of its own** (hosting platforms provide it). Teammates get their own logins and the security work has been reviewed by independent AI reviewers, but it has not had a human professional audit.
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
| [deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness) | MIT | An "everything is a plugin" harness: model adapters behind one seam, a tool pipeline that can allow, ask or deny before running, subagents, plugins that add tools and skills, a GitHub-topic plugin index. I read its documentation and parts of its source | `providers.py` (adapters), the Off/Ask/Allow internet gate in `tools.execute`, `plugins.py` with on-demand skills, same-site-only redirects in `webfetch.py`, `@all` parallel agents. Written from scratch in Python; no code copied (I cloned and read parts of its source, including its fetch policy and skill loader) |
| Grok (xAI), as a product reference | not code | A witty-but-useful assistant with live web search, voice and a phone app | Inspiration for the planned tone choice, web search and voice; no Grok code or assets are used |

## Project layout

```
src/kintsugi/workspace/   the product: core.py agents.py tools.py perms.py sandbox.py keychain.py scheduler.py backup.py
                          server.py db.py team.py tasks.py personal.py compact.py uploads.py providers.py plugins.py
                          integrations.py dojo.py improve.py cli.py  web/ (app.js, extras.js, app.css: the interface)
src/kintsugi/             engine modules the product reuses: model.py memory.py graph.py loop.py verifier.py
SECURITY.md  CONTRIBUTING.md  Dockerfile  render.yaml  .devcontainer/  docs/ (TEAMS, PHONE, PLUGINS, INTEGRATIONS, HOSTING, STATUS...)
examples/                 workspace_demo.py, smoke and model-comparison scripts
tests/                    ~550 offline tests (python -m unittest discover -s tests) and tests/ui (19 browser suites)
research/                 the original weak-model experiment (write-up); benchmark/, results/ and RESULTS.md move here soon
```

Tests use the standard library's `unittest`, so a fresh clone needs no installs to run them.

## License

MIT, see [LICENSE](LICENSE).
