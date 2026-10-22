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
| Data you want gone | Delete an agent (everything it owns), a room, or old messages; download everything as JSON. UI: Details > Safety. CLI: `delete-agent`, `delete-room`, `purge`. | `test_workspace_privacy.py` |

## What does NOT protect you (read this)

- **The namespace sandbox is not a hardened container.** It is a Linux user, mount, pid and network namespace plus
  a chroot, built from standard tools. It stops accidents and ordinary snooping; a determined attacker with a
  kernel exploit could escape it. Do not run code you do not understand, and do not put secrets you cannot
  lose on the same machine.
- **In the fallback modes the network is open.** Approved code could send a secret you gave it to the internet. In the
  plain-process mode it can also read anything the server's user can read.
- **`fix_code` runs model-written code outside the sandbox** (through the benchmark verifier). It is therefore
  **disabled while the server runs as root** (set `KINTSUGI_ALLOW_FIX_CODE_AS_ROOT=1` to override at your own risk).
- **Prompt injection is mitigated, not solved.** A model can still be talked into asking for something harmful; the
  approval card is your protection, so read it. Do not use `dangerous` mode with content you do not trust.
- **Your conversations go to your model provider.** Whenever an agent thinks, the chat text and tool results are sent
  to the provider's API (Groq by default; shown in Details > Safety and by `kintsugi workspace status`). Files,
  keychain and other chats stay on the server. Read the provider's data policy; free tiers may keep data.
- **One shared token, no user accounts.** Anyone with the token is you. Rotate it by changing `KINTSUGI_TOKEN`.
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
