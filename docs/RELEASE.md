# Release checklist (merge to main, then publish)

State when this was written (2026-10-22): `main` is 0 commits ahead of `claude/ecstatic-cray-g930so` (93 commits ahead), so the merge is a clean
fast-forward with no conflicts. CI is green on the branch head. No API keys or tokens were found in tracked files (scan for `sk-`, `ghp_`, `gsk_`,
`AIza`, `xox`). Nothing here has been done for you: merging and publishing are your decisions.

## 1. Before merging (you, about 30 minutes)
- [ ] **Use it yourself on your phone** with your own API key: set up (Settings > Models), chat, an approval, a task, invite one friend. Write down anything odd.
      This is the biggest gap: every test so far used scripted models and an emulated phone.
- [ ] Decide the **final name** ("Kintsugi" is a working name). Changing it later touches `pyproject.toml`, `README.md`, the manifest and icons.
- [ ] Read the README status table once and strike anything you would not say out loud to a stranger.
- [ ] Decide the research archive move (`benchmark/`, `results/`, `RESULTS.md` into `research/`): yes or no. It is not done; it reshuffles paths in scripts, workflows and tests.

## 2. Merge (pick one; I have not done either)
- Simplest, keeps the 93 commits: on GitHub open a pull request from `claude/ecstatic-cray-g930so` into `main`, wait for CI, choose *Merge* (a fast-forward-style merge).
  Or *Squash and merge* for one tidy commit (loses the history of the research runs, which is also in `results/`).
- Command line instead: `git checkout main && git merge --ff-only claude/ecstatic-cray-g930so && git push origin main`.
- After merging: CI runs on `main`. Confirm it is green before announcing anything.

## 3. GitHub settings (only you can do these)
- [ ] About box: description and topics (suggested: `ai-agents`, `team-workspace`, `self-hosted`, `byok`, `pwa`, `python`).
- [ ] Settings > General > Social preview: upload `docs/img/team-tasks.png`.
- [ ] Settings > Code security: turn on **Private vulnerability reporting** (SECURITY.md points people to it) and secret scanning.
- [ ] Settings > Branches: protect `main` (require CI to pass) once you are done committing straight to it.
- [ ] Optional: repo secret for the benchmark workflow (`GROQ_API_KEY`), a private backup repo plus fine-grained token, pin the repo, a `v0.1.0` release.

## 4. Release notes to paste (honest version)
Kintsugi is a self-hosted, phone-first workspace where a team shares AI agents on its own API key. Agents ask before risky actions and run approved
code in a locked box. Early release (0.1.0): tested with scripted models, an emulated phone and fake servers; **not yet tried with real providers, real phones or a real
team, and not independently audited.** Known limits are in SECURITY.md and docs/TEAMS.md.

## 5. Hosting a first copy (see docs/HOSTING.md)
- [ ] Deploy (Render / Docker / Codespaces), set `KINTSUGI_TOKEN`, open the link, add your key in Settings > Models. Never put keys in the repo or in chat.
- [ ] Free hosts erase their disk on restart: set up the encrypted backup (Settings > Backup) before inviting anyone.
- [ ] Invite one person, check they can chat and cannot see rooms they are not in.

## 6. If submitting to the hackathon (closes 2026-10-25)
- [ ] The repo is public, README first screen explains the idea in two lines, screenshots load, license present (MIT is in `LICENSE`).
- [ ] A 1-2 minute screen recording from your phone (setup, a task given to an agent, an approval).
- [ ] Say plainly what is tested and what is not (the README status table does).

## Known limits to keep in mind (also in docs/STATUS.md)
Approved code can read the agent's whole folder, including private-chat files. The owner's link is the permanent owner key. Agents share lessons from
their mistakes across chats. Sign-in code redemption is refused while an address is rate-limited. Nothing has been verified against real providers or phones.
