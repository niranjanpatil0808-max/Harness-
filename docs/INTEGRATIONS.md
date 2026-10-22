# Integrations: GitHub, Slack, Calendar, Gmail

Let your agents read from the tools your team already uses. Everything is **read-only**, except Slack posting, which is **off by
default** and, when on, asks you before every single post. No app registration or OAuth consent screen is needed: you paste one
credential, once. Only the **owner** can configure or switch these on (Settings > Integrations).

| | What the agent can do | What you paste | What you choose |
|---|---|---|---|
| **GitHub** | repo facts, recent issues and PRs, one issue with its latest comments, read a file or list a folder | a fine-grained token with read-only access (Contents, Issues, Pull requests, Metadata) to only the repositories you pick | an allow-list: `owner/name`, or `owner/*` |
| **Slack** | read recent messages of listed channels; post (only if you allow it, always with approval) | a bot token (`xoxb-…`) from a Slack app you create (scopes `channels:read`, `channels:history`, optionally `groups:*`, `chat:write`) | an allow-list of channel names |
| **Calendar** | list upcoming events (next 1-31 days) | the calendar's *secret iCal address* (Google Calendar: Settings > your calendar > Integrate calendar) | nothing |
| **Gmail** | list the latest inbox emails and search subject/sender: sender, subject, date, first lines | your address + a Google *app password* (needs 2-step verification; IMAP must be on) | nothing |

An integration does nothing for an agent until you **switch it on for that agent**.

## How it stays safe

- **Credentials**: stored in the workspace keychain, write-only (no API, export, log or error shows them), injected by the server and
  never put in a prompt. GitHub/Slack/Calendar requests go through the same guarded client as `web_fetch` (public hosts only,
  pinned connection, no redirects). Gmail connects only to `imap.gmail.com` over TLS.
- **Reach**: allow-lists for repositories and channels are checked on every call. A repository or channel you did not list cannot be
  read even if the token could.
- **Internet setting**: every call is internet use, so each agent's **Off / Ask / Allow** applies (Ask shows the exact request), and
  every call counts toward the daily online-request cap.
- **Untrusted data**: issues, messages, events and **especially emails** can contain text written by an attacker ("ignore your rules
  and…"). Results are labelled untrusted and the agent is told never to follow instructions found in them. Approvals and
  permissions sit above all of it, so a planted instruction still cannot run code or post without a person saying yes.
- **Read-only**: Gmail opens the inbox read-only and fetches with `PEEK` (nothing is marked read); there is no send, reply, delete or
  move. GitHub calls are GET only. Slack posting is the only write and always waits for approval, even in the "never ask" tier.

## Setting each one up

**GitHub**: github.com/settings/personal-access-tokens > Generate new token (fine-grained). Repository access: *Only select
repositories*. Permissions: Contents, Issues, Pull requests, Metadata, all *Read-only*. Paste it, list the repositories, Save, Test
connection, then switch it on for the agents that should use it.

**Slack**: api.slack.com/apps > Create new app > From scratch. OAuth & Permissions > add the bot scopes, Install to Workspace, copy
the *Bot User OAuth Token*. In Slack, `/invite @yourbot` into each channel you list.

**Calendar**: Google Calendar > Settings > the calendar > Integrate calendar > *Secret address in iCal format*. Anyone with that
address can read the calendar, which is why it is kept like a password. Recurring events are understood for the common cases (daily,
weekly with days, monthly, yearly, with counts, end dates and cancelled occurrences); an unusual repeat rule shows only its first
occurrence.

**Gmail**: Google Account > Security > 2-Step Verification on > App passwords > create one; Gmail Settings > Forwarding and POP/IMAP >
Enable IMAP. Paste your address and the 16-letter password.

## Honest limits

- **Not yet tried against the real GitHub, Slack, Google Calendar or Gmail.** They are tested against local fakes (including a fake IMAP
  server), so a real service's quirks could still cause a failure on first use. Use **Test connection** first.
- Gmail needs an app password; accounts managed by an organization often disable them.
- Slack needs the bot invited to each channel; direct messages are not supported.
- Agents share one memory and one folder, so what an agent reads from an integration can come up when a teammate talks to it. Switch
  integrations on only for agents your team is comfortable sharing that data through.
- Outlook, Google Drive, Notion, Linear and others are not built.

## Credit

Keeping credentials behind named tool providers, out of the model's reach, follows the structure of
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (MIT). The code here is written from scratch.
