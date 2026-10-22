# Security and privacy

Kintsugi Workspace lets AI agents run tools and, with your approval, code. This page says what is protected, what
is not, and what to do about it. Last reviewed 2026-10-22. It is a small project by one person: it has been tested
(see `tests/test_workspace_*.py`) but **not independently audited**.

## What protects you

| Risk | Protection | Where it is tested |
|---|---|---|
| An agent runs harmful code | Risky tools (`run_python`, `publish_app`, `fix_code`, `schedule`) wait for your approval in the default tier. The card shows the **full code** and says whether it will run isolated. | `test_workspace_security.py`, browser test |
| Approved code reads your files or secrets | **Namespace sandbox** (Linux): code sees only its own agent's folder and a read-only system, with a private process list. Not the database, keychain, token, other agents' folders, home directory or the server's environment. | `test_workspace_privacy.py` |
| Approved code uses the network | Blocked in the namespace sandbox (even the host's loopback). **Not** blocked in the fallback below. | same |
| No namespaces available (most containers) | **Drop-privileges fallback**: when the server runs as root it runs agent code as a separate unprivileged user id per agent; the server's data files are root-only. The network is **not** blocked here. | same |
| Neither is available | The code runs as the server's user (a plain process). The Safety tab and the approval card say **"not isolated"**. Set `KINTSUGI_SANDBOX=require` to disable `run_python` in this case. | `test_workspace_security.py` |
| Runaway code | Wall-clock timeout, CPU, memory and file-size limits; the whole process group is killed. | `test_workspace_privacy.py` |
| Runaway spending | A daily cap on model calls for the whole workspace (default 500, `KINTSUGI_DAILY_CALLS`, `0` = off), a per-agent rate limit (20 runs a minute), and a loop guard (4 agent-to-agent replies in a row). | `test_workspace_privacy.py`, `test_workspace_core.py` |
| Someone else reaches the web page | A secret access token (header only, never in a URL), constant-time comparison, wrong-token throttling (10 a minute per client), and a refusal to listen on a network address with a token shorter than 24 characters. | `test_workspace_server.py` |
| Web attacks on the page | Content-Security-Policy (`script-src 'self'`), `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, markdown sanitised by DOMPurify, all page text built with safe DOM calls. No cookies, so no CSRF. | `test_workspace_server.py`, browser test |
| Agent-published apps attack the workspace | Apps are served with a `sandbox` CSP (no network, no same-origin access) and opened with **signed links that expire after an hour** and work for one app only. | `test_workspace_server.py` |
| Secrets leak | Secrets live in the keychain, are handed to code only by name, are redacted from tool output, audit entries and agent messages, and are never returned by the API or included in exports. | `test_workspace_privacy.py`, `test_workspace_server.py` |
| Impersonation | People cannot post as an agent, `system` or a cron job. | `test_workspace_security.py` |
| Prompt injection (text that tries to give the agent orders) | The agent is told that files, tool results and other people's messages are data, not instructions; risky tools still need your approval. | `test_workspace_agents.py` |
| The workspace changes itself unsafely | Self-improvement can change only an agent's model and playbook text; it can never touch permissions, tools, the sandbox, approvals, secrets or code (enforced by tests that inspect its source and check a full study leaves everything else untouched). Rules about safety, secrets, links or approvals are dropped, a change that makes the prompt-injection trap worse is never proposed, and every change is reviewable and reversible. See [docs/SELF_IMPROVEMENT.md](docs/SELF_IMPROVEMENT.md). | `test_workspace_improve.py` |
| Web search leaks data or takes orders from a web page | Search uses only the owner's own key and only the provider's fixed API host. Agents get a few trimmed snippets with sources; they cannot open or download pages (no SSRF, no page injection). Results are labelled untrusted and `javascript:`/`data:` links are dropped. Queries are length-limited, refuse secret values, are counted against a daily cap and recorded in the log. The key is write-only. | `test_workspace_search.py` |
| Notifications leak your messages | A push carries no text at all (the phone shows a generic line); only a signed 'wake up' goes to Google, Apple or Mozilla. Subscriptions must point at those services (no forged addresses), are capped, and pushes are throttled to one a minute. The signing key lives in the keychain. | `test_workspace_push.py` |
| A teammate does more than they should | Three roles (member, admin, owner) enforced on the server for every endpoint, deny-by-default for anything not listed; members only read and write the rooms they belong to and speak only as themselves; private chats are visible only to their two participants (and the owner); approvals follow an owner-set policy and record who decided; invite links are single-use, expiring and rate-limited; tokens are stored hashed and removing a person revokes them at once. An agent will not post into a room the asker is not in. | `test_workspace_team.py` |
| Your API key leaks | Provider keys live in the keychain, are write-only (no endpoint, export, log or error returns them), and are sent only to the address you saved for that provider (https, or localhost for a model on your own computer). Gemini's key is sent in a header, never in a URL. | `test_workspace_providers.py` |
| An agent goes online when you did not want it to | Each agent is Off, Ask (every search or fetch waits for a yes that shows the exact address) or Allow, with a workspace master switch above all of them. New agents start on Ask. Internet tools are hidden from the model when Off. | `test_workspace_internet.py` |
| Fetching a page reaches your internal network (SSRF) or runs a page's orders | Public addresses only (loopback, private, link-local, cloud-metadata and reserved ranges are refused, including through DNS answers and redirects); the connection is pinned to the checked address; https/http on normal ports; no cookies or credentials; text only, size-capped, daily-capped; results are labelled untrusted data. | `test_workspace_internet.py` |
| A plugin does harm | No plugin code runs. Strict manifest whitelist, declared hosts only through the same guarded client, keys injected by name, every tool obeys Off/Ask/Allow, writes always ask, you approve a fingerprint after seeing everything, no auto-update. A malicious *skill* can still try to persuade a model, so only install plugins you trust. See [docs/PLUGINS.md](docs/PLUGINS.md). | `test_workspace_plugins.py` |
| Your backup is read by someone else | Encrypted on the server before upload (PBKDF2-SHA256 600k rounds + Fernet); only `api.github.com` is contacted; the repository must be private; token, repository and passphrase come from the host's environment, never the database or API; a restore never overwrites existing data and rejects archives with links or paths that escape. Lose the passphrase and the backup is unreadable. | `test_workspace_backup.py` |
| Data you want gone | Delete an agent (everything it owns), a room, or old messages; download everything as JSON. UI: Details > Safety. CLI: `delete-agent`, `delete-room`, `purge`. | `test_workspace_privacy.py` |

## What does NOT protect you (read this)

- **The namespace sandbox is not a hardened container.** It is a Linux user, mount, pid and network namespace plus
  a chroot, built from standard tools. It stops accidents and ordinary snooping; a determined attacker with a
  kernel exploit could escape it. Do not run code you do not understand, and do not put secrets you cannot
  lose on the same machine.
- **A fork bomb can briefly slow the machine** until the timeout kills it (there is no process-count limit).
- **In the fallback modes the network is open.** Approved code could send a secret you gave it to the internet. In the
  plain-process mode it can also read anything the server's user can read.
- **`fix_code` runs model-written code outside the sandbox** (through the benchmark verifier). It is therefore
  **disabled while the server runs as root** (set `KINTSUGI_ALLOW_FIX_CODE_AS_ROOT=1` to override at your own risk).
- **Prompt injection is mitigated, not solved.** A model can still be talked into asking for something harmful; the
  approval card is your protection, so read it. Do not use `dangerous` mode with content you do not trust.
- **Self-improvement studies spend model calls and send made-up practice tasks (and, if you opt in, an agent's lessons and pasted notes) to your provider.** They are off by default, capped per study and by the daily limit, and never use your chats or files. A pasted note that tries to smuggle in a rule is filtered, but review proposals before accepting them, especially with auto-apply on.
- **Web search sends the words an agent chooses to your search provider** (Tavily or Brave). Secrets are refused, but an agent that has been talked into it could put chat content into a query. Searches are capped and logged; leave search off if that matters to you.
- **Push notifications tell Google, Apple or Mozilla that this device got a notification** (not what it said) and when. Voice, if you use it, may be processed by your phone's speech service. The push signing has been tested against a fake push service only.
- **Your conversations go to your model provider.** Whenever an agent thinks, the chat text and tool results are sent
  to the provider's API (Groq by default; shown in Details > Safety and by `kintsugi workspace status`). Files,
  keychain and other chats stay on the server. Read the provider's data policy; free tiers may keep data.
- **The owner token is one shared secret.** Anyone with it is the owner (they can do everything and read every room). Rotate it by changing `KINTSUGI_TOKEN`. Teammates get their own logins with roles ([docs/TEAMS.md](docs/TEAMS.md)), but there is no email check, password reset or single sign-on, and agents keep one shared memory per agent, so private information told to an agent can surface for others who talk to it.
- **The page remembers your token in this browser's local storage** so you do not retype it. On a shared or borrowed device use a private window, and rotate the token afterwards.
- **No TLS built in.** On a network, put it behind HTTPS (hosting platforms and Codespaces do this for you).
- **The keychain is not encrypted** unless the optional `cryptography` package is installed, and then the key sits next
  to the data. It protects against casual reading, not against someone with the folder.
- **Logs and the audit trail contain your activity** (not secrets) until you purge them.
- The hosting recipes in `docs/HOSTING.md` were checked by running the installed package in a clean environment; the
  Docker image and the Render blueprint have **not** been deployed by the author yet.

## Reporting a problem

Open a GitHub issue titled "Security" without exploit details, or email the repository owner. Please do not post
working exploits publicly before there is a fix.
