# Project status and handoff (kept up to date so nothing is lost)

Last updated: 2026-10-22. Branch: `claude/ecstatic-cray-g930so` (never merged to `main`; do not merge or open a PR unless the owner asks).
Product: **Kintsugi** (working name; the owner will choose the final name). Built for the Meta Global AI Developer Hackathon (applications close
Oct 25, 2026). Owner: a "shadow operator" in India; wants honesty; free-only budget.

## What exists (all pushed)

Stage 0 tidy; Stage 1 phone app (PWA, voice, tone, web search, automations, time zones, push, unread); backup (encrypted, to a private GitHub repo);
easier UX (To: chips, starter ideas); bring-your-own-key providers (OpenAI-style, Anthropic, Gemini); per-agent internet Off/Ask/Allow + guarded
`web_fetch`; parallel agents (`@all`, configurable); plugins (skills on demand + guarded HTTP tools); Stage 2 teams (invite links, owner/admin/member,
approval policy, private chats + shared rooms); Stage 3 integrations (GitHub read-only + allow-list, Slack read / approved post, Calendar via secret iCal,
Gmail read-only IMAP). Learned from the DeepSeek Harness source (cloned at /home/user/deepseek-ai/deepseek-harness, outside the repo, MIT):
cross-site redirects refused, skills loaded on demand. Docs: README, SECURITY.md, docs/{PHONE,WORKSPACE,HOSTING,SELF_IMPROVEMENT,PLUGINS,TEAMS,INTEGRATIONS}.md.

Tests: `python -m unittest discover -s tests` (~470 tests, ~2.5 min) and `bash tests/ui/run_all.sh` (15 browser suites, ~15 min; needs node + playwright).
Run them in the background and wait with ONE `while ! grep -q done log; do sleep 4; done` (do not stack waiters; do not use `pkill -f`, it kills the shell).

## Honest verification gaps (say these to the owner)

Nothing has been tried against REAL services: provider keys (OpenAI/Anthropic/Gemini/Groq...), live web fetch, GitHub plugin download, GitHub/Slack/Google Calendar/
Gmail, real push services, real phones (PWA/voice), a real team over a real deployment. All tested against local fakes. Llama (Meta) not yet tested with a real key.

## Current task: "make it better, fix security bugs and normal bugs, ready for real users"

Four independent reviewers were launched (each in its own worktree). Results so far:

1. **Core/sandbox/tools review (DONE, partial)**: 12 findings, ALL FIXED and regression-tested in `tests/test_workspace_review_fixes.py`:
   unique sandbox uids (crc32 collided), deleting an agent now clears plugin/integration grants + proposals, a run cannot resurrect a deleted agent's files and an
   unknown sender cannot post, approvals decided exactly once and never stuck on error, tool argument types, `fix_code` retries clamp, self-improvement cannot reset an
   agent's provider (`set_model(keep_provider=True)`), message text cannot forge `<message>` blocks, run-failure text scrubbed of keys, dojo agents get no code tools
   when the sandbox is not isolated, playbook/tone filters see through invisible/fullwidth characters. Not covered by that reviewer (it stopped early): cron/DST, websearch,
   backup/team/plugins paths, drop-privileges fallback details.
2. **Hardening already done by me**: removing a person deletes their DMs/jobs/tone; admins cannot approve `fix_code` or unisolated `run_python` and cannot set tier
   "dangerous"; fetch has a 30 s total deadline (`read1`); per-person 30 messages/minute limit (HTTP 429).
3. **STILL RUNNING when this file was written** (reports arrive as notifications; fix what they CONFIRM, add a regression test for each, run both test suites, push):
   - access-control / roles / web-UI XSS reviewer
   - internet-facing code reviewer (SSRF, plugins, integrations, ICS/IMAP parsers, backup crypto, tar handling, secret leakage)
   - browser QA reviewer (phone + desktop flows, screenshots)
   If their reports are lost, re-run equivalent reviews (briefs are easy to rewrite from the scopes above).

## Other pending items

- Scheduled task `trig_011LM215tRj3ag7w3oMdssrw` fires 2026-10-22T17:35Z into the original session: starts the old research experiment batch and, at the end, an
  ARCHIVE STEP that moves `benchmark/`, `results/`, `RESULTS.md` under `research/` and fixes paths/workflows/tests. Product work in `src/kintsugi/workspace` does not conflict.
  Before it runs: `git pull --rebase origin claude/ecstatic-cray-g930so`.
- Ideas not built: per-person agent memory; single sign-on; Python-code plugins; Outlook/Drive/Notion/Linear; compaction; ephemeral helper agents; admin
  join-any-shared-room is allowed (document it).
- Before the hackathon demo: try a real key on a phone; try GitHub/Slack/Gmail with real credentials using "Test connection"; run `examples/workspace_demo.py`.
- Reminder for the owner: choose the final name; add real keys only in the app (Settings > Models), never in chat or the repo.

## Internet-facing review (reviewer 2) findings, received 2026-10-22: FIX CHECKLIST (mark done as fixed)

1. HIGH  Gmail IMAP did not verify TLS (`imaplib.IMAP4_SSL` without ssl_context) -> pass `ssl.create_default_context()`.
2. MED-HIGH  Provider keys/tokens followed redirects to any host (urllib default handler copies Authorization/x-api-key/X-Subscription-Token): model.py request_json + list_models,
   providers.py, websearch.py, backup.py (GitHub token), push.py -> one opener with a NoRedirect handler used everywhere.
3. MED  push.endpoint_ok accepts spaces/non-ASCII/CRLF/backslash; send_one only catches URLError/OSError -> a member can kill the notify thread -> strict regex, catch Exception, delete invalid rows.
4. MED  webfetch TOTAL_SECONDS not applied to the header phase (header slowloris) -> one deadline for the whole roundtrip (socket timeout = remaining).
5. MED  ICS parser: 2000-iteration cap (old daily events vanish), UTC-only recurrence (DST wrong), all-day dates shifted by tz, VALARM description leaks, RECURRENCE-ID not handled,
   unsupported BYDAY/BYMONTHDAY forms misapplied, UNTIL date exclusive, OverflowError crash on huge INTERVAL (only ValueError caught), lowercase begin:vevent, quadratic _unfold.
6. MED-LOW  redirect `Location` text echoed (200 chars) into the FetchError -> reaches model/lessons -> report hostname only.
7. MED-LOW  plugin param `..` survives quoting and climbs path with the API key attached -> reject `.`/`..` values.
8. LOW-MED  Gmail search: backslash breaks the IMAP command, non-ASCII query raises UnicodeEncodeError, BODY.PEEK[] downloads whole message -> UTF-8 search, escape, partial fetch.
9. LOW  plugin manifest: HEADER_RE needs fullmatch (trailing newline), restrict `prefix` to printable ASCII, wrap urlsplit ValueError, full-length fingerprint.
10. LOW  _public misses IPv6 embedding IPv4 (::127.0.0.1, 64:ff9b::/96 NAT64, ::ffff:0:0:0/96, 2002::/16), deny fec0::/10 and 192.88.99.0/24.
11. LOW  IDN hosts: Host header must use idna.
12. LOW  backup: no rollback protection, download without size cap, restore_if_empty only catches BackupError (tar/OSError crash at startup).
13. LOW  keychain not crash-safe/thread-safe: temp file + os.replace + lock.
Minor: to_text double html.unescape; web_search result URL control chars; Retry-After HTTP-date ValueError in model.py.
(Reviewer verified fine: core SSRF literal/DNS checks, redirects, pinned connection, plugin archive reading, template quoting, backup crypto basics, secrets in errors.)

## Access-control / web-UI review (reviewer 1) findings: FIX CHECKLIST (mark done as fixed)

1. HIGH  Agent/person message HTML can carry CSS (`<style>`, style=, form/input, fixed overlays) that hides the approval card's real code/"not isolated" warning or blanks the app
   (web/app.js:70 DOMPurify default config + CSP style-src unsafe-inline) -> DOMPurify with FORBID_TAGS [style,form,input,button,select,textarea,link,meta,iframe], FORBID_ATTR [style,id,name], and `.body{contain:paint;isolation:isolate;overflow:hidden}`; consider upgrading vendored DOMPurify (3.1.6).
2. MED  Admins can read private-DM content via /api/audit (tool args in detail), /api/state approvals (full args, can_decide) and /api/approve output -> filter audit/approvals to rooms the viewer is in (owner sees all); log tool names only.
3. MED  Admin can exfiltrate agent secret values (reversed print) by approving run_python with a non-empty `secrets` list -> make such approvals owner-only (extend Team.owner_only_tool).
4. MED  send_message/schedule "asker must be in the room" guard bypassed via agent->agent hand-off (requester_of returns None) -> carry originating person through hops (requested_by on message/inherit in _dispatch); fail closed when asker unknown and room != ctx.room; add asker check to schedule(room=).
5. MED  Revocation gaps: (a) invites outlive their creator (delete unused invites created_by=name on remove; revoke when role lowered); (b) removing a member from a room leaves their jobs firing and /api/automations/run working -> delete jobs on remove_member, require can_see_room in _owns_job.
6. MED/LOW  Login-CSRF via `#token=` fragment silently replaces stored token -> confirm "Sign in as <name>? replaces your current sign-in" (fetch /api/me first).
7. LOW/MED  Throttle: failure lock checked before token validation (right token refused after 10 wrong); shared IP behind proxy; Dockerfile sets KINTSUGI_TRUST_PROXY=1 by default (XFF spoofing/bypass) -> validate token first, throttle failures only, no default TRUST_PROXY (or last-hop XFF only from trusted peer); /api/join failures shouldn't lock real users.
8. LOW  Published app can phish on the workspace origin (self-navigation) -> separate origin/port, or warn on publish_app approval card.
9. LOW  open_dm joins names with "-": ambiguous (xa-yb,zc) vs (xa,yb-zc) -> separator not allowed in names, or insert members explicitly.
10. LOW  /api/applink no agent-access check; push subscribe 20-device cap is global (cap per user); /api/jobs no cap (add per-user/global cap); /apps ?sig=%C3%A9 uncaught TypeError in compare_digest (compare bytes);
    sign-out leaves kt-draft-*/kt-seen in localStorage; approval card shows only args.code (show secrets list + timeout); admin can delete anyone's DM and toggle improve share_lessons/auto_apply (owner-level);
    admins can create agents named cron-5/owner (reserve names); improve/decide records by="web".
    DOC GAP: integration/plugin tools run for ANY room member who talks to an enabled agent (a member can read the owner's Gmail/Calendar/GitHub/Slack through it) -> add to docs/TEAMS.md honest limits.
(Reviewer verified fine: 66-endpoint role sweep, owner-only list, admin->owner gates, no member read of other rooms, invites single-use/hashed, token handling, atomic approvals, no script XSS, CSP/headers/SW caching.)

## Progress on the internet-facing checklist (reviewer 2)
Done in code (tests being finished): items 1-4, 6-11, 13 and minor ones, plus ICS parser rewrite (item 5). Item 12 partially (download cap + restore never crashes; rollback protection NOT done).

## Update (end of review round 1)

DONE and tested (unit ~500 tests, 16 browser suites all green):
- Reviewer 3 (core): all 12 fixed. Reviewer 2 (internet): items 1-11 and 13 fixed (redirects never forward keys, IMAP TLS verified, push validation, fetch deadline incl. headers
  via watchdog, IPv6-embedded IPv4, idna Host, redirect text not echoed, plugin `..`/header/prefix/fingerprint, ICS parser rewritten, keychain atomic+locked); item 12 partial
  (download cap + restore never crashes; **rollback protection NOT done**).
- Reviewer 1 (access/UI): items 1-7, 9, 10 fixed (message markup sanitized hard, admins cannot read private DM content/args/approvals or approve code given secrets, cross-room hand-off
  fails closed, invites/schedules die with their owner, right token never throttled, no default TRUST_PROXY except render.yaml, DM name collisions, caps, reserved names,
  sign-in confirmation, clean sign-out, approval card shows secrets). Item 8 (published apps on the workspace origin) only DOCUMENTED + warning on the approval card; separate origin NOT built.
  Minor not done: improve/decide records by="web" instead of the person.
STILL PENDING: browser QA reviewer (agent abfbc2c4f3fa9f541) had not reported yet; when it does, fix confirmed UX/layout bugs and add tests.
Test hygiene note: stale `serve_mock.py` servers on port 8804 cause false browser-test failures; stop them by pid file, never with `pkill -f` or a /proc scan whose own command line contains the name.

## Browser QA review (reviewer 4) findings: UI FIX CHECKLIST (received after review round 1; folded into the UI overhaul)

1. HIGH  Admins get an empty Details drawer: loadTab() calls owner-only /api/plugins for the agent tab -> 403 every poll, drawer never renders. Fix: only owners fetch it / try-catch.
2. HIGH  Member sign-out is a dead end: tokens never shown; same name cannot rejoin. Fix: show token/link once after join and after rotating; add owner/admin "reset sign-in" for a person (new link).
3. MED-HIGH  New approval card can land below the fold on phone (`#scroll{scroll-behavior:smooth}` races card growth) -> instant scroll / scrollIntoView on new approval.
4. MED-HIGH  Provider test with a wrong address freezes ~2 min (retries/back-off apply to connection refused) and shows raw JSON error -> test with max_retries=0, ~12 s timeout, friendly "did not answer like an OpenAI-style API (does it end in /v1?)", scroll result into view.
5. MED  Wrong/expired/revoked token is silent (Connect dialog reopens without message; open dialogs block it; wording meant for the owner) -> message in dialog, replace open dialogs on 401, member wording.
6. MED  aria-pressed/aria-selected rendered as ""/missing (h() helper) -> String(v) for aria-* attributes.
7. MED  Dialogs not modal (no focus trap/restore); closed off-canvas sidebar stays in tab order -> trap + restore + inert/visibility hidden.
8. MED  Admin Team panel labels the owner row "you" (wrong for admins) -> show owner's real label, mark current user "(you)".
9. MED  No agents / room with no agents: composer enabled, messages vanish silently -> disable/banner with "New agent".
10. LOW-MED  Invite dialog dismissable -> blank app; joining in a browser holding the owner's token silently overwrites it; name rules inconsistent (Sam accepted+lowercased, "Sam Smith" rejected, New agent rejects "Carol") -> non-dismissable join with "sign in instead", warn before replacing, normalise names everywhere.
11. LOW-MED  Contrast: white on accent ~3.1:1 (dark), 4.2:1 (light), dark placeholder 2.87:1, accent text 3.36:1, 12px headings 4.15:1 -> adjust palette.
12. LOW  Tap targets <40px (chips 38, textarea 36, Copy 47x25), top-bar sidebar button squeezed to 18px by approval pill, Settings/drawer tabs clipped without scroll hint -> flex-shrink:0, scrollIntoView active tab, min-height 40.
13. LOW  Sidebar stays open after Settings on phone; toast covers fields; numeric settings clamp silently but say "Saved"; missing period after "Get a key at ..."; drawer says "server's clock" even after time zone set;
    Safety tab shows owner-only buttons to admins; provider address https://169.254.169.254/v1 accepted (block link-local/private IP literals unless localhost).
(QA verified working: first-run Models prompt + clear no-key error, validation messages, chat basics, automations, settings persistence, plugins/integrations/team flows, PWA offline shell, focus rings, no console errors.)

## Current plan (after limits reset; user asked: 1) friendlier UI, 2) major upgrades, 3) then security)
Backend done so far (uncommitted until tests): stop-an-agent (/api/stop + live activity in /api/state), usage tracking (usage_log, /api/usage, prices), name clash fixed (agent_activity).
Next: message search (/api/find), starter templates (/api/templates), file upload/download, then UI overhaul (settings page with sections, first-run wizard, quick switcher, message actions, Stop button, usage tab, QA fixes), tests, then security round 2.


## Update: UI overhaul + upgrades (2026-10-22, later)
Done and pushed (commit "Settings page, usage dashboard, setup wizard, ..."):
- web/extras.js (loaded after app.js, cached by sw.js): Settings page with grouped nav (overrides settingsDialog; keeps #settings-body,
  wraps panel refreshes via a `fill` override so the heading stays), Usage panel (+ owner price form, "Remember long chats" switch),
  first-run wizard `setupWizard()` (owner, when model_ready is false; members get `noModelNotice()`), `openSwitcher()` (Ctrl/Cmd+K),
  `startersDialog()` (also "Start from a team" in New chat), `exportChat(room)` (Markdown download, paginates /api/messages).
- app.js: Team panel "Reset sign-in" + `signInLinkDialog` (link shown once); Details drawer "Save this chat (Markdown)".
- compact.py: running room summary of messages older than the 12 in view (BATCH 16, MAX_FOLD 60, 1800 chars), scrubbed with ws._scrub,
  labelled as data in build_context, deleted on delete_room / delete_agent / purge / when switched off; POST /api/compaction owner-only.
- Tests: tests/ui/upgrades.js (new, in run_all.sh), team.js (reset sign-in), selectors moved from `.tab` to `.set-item` for settings;
  run_all.sh accepts SUITES="a b". tests/test_workspace_compact.py (7). Full run: 515 unit OK, 17 browser suites OK.
Still open from QA list: toast position on phone, numeric clamp messages ("Saved (limit set to N)"), schedule "server's clock" text.
Next: security round 2 (3 independent reviewers launched: new backend endpoints; web frontend/XSS/headers; backup/sandbox/scheduler/
published apps). Fix confirmed findings with regression tests, rerun everything, push, then report to the user.
