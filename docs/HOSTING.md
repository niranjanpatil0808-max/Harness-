# Running the workspace somewhere you can reach from a phone

Three ways, easiest first. All of them need **your own model API key** (for example a free Groq key) and a
**long random access token** that you choose. Never paste either into a chat, issue or the repository.

> Status: the package, the web page and the server were run in a clean environment exactly as the container runs
> them (see `SECURITY.md`). The Docker image and the Render blueprint have not been deployed by the author yet, so
> expect to fix a small thing on first deploy and tell us.

## 1. GitHub Codespaces (works from a phone browser)

1. Add a secret: GitHub > Settings > Codespaces > Secrets: `KINTSUGI_TOKEN`
   (any random string of 24+ characters; mashing a keyboard for a while is fine, or use a password manager).
   Give it access to this repository.
2. Repository > Code > Codespaces > Create codespace. It installs the package, runs the tests and starts the server.
3. Open the forwarded port 8765 and sign in with your `KINTSUGI_TOKEN`. Keep the port **Private** (the default).
4. Codespaces sleep after inactivity; files persist until you delete the codespace.

## 2. Render (a public web address, free plan)

1. Push or fork this repository to your GitHub account.
2. render.com > New > Blueprint > pick the repository. Render reads `render.yaml`.
3. In the new service's Environment tab, copy `KINTSUGI_TOKEN` (it is generated for you): that is your sign-in token.
4. Open the service address and sign in. The app opens **Settings > Models**: choose your provider and paste **your own API key**
   there (nothing about your key goes through the repository or the Render settings). The Safety tab shows how code is isolated.

Things to know about the **free plan**: the service sleeps when idle (the first visit after a while is slow and
scheduled jobs do not run while it sleeps), and **files are lost on every deploy or restart** (chats, agents,
lessons). Two ways to keep your data: turn on the **encrypted backup** below (free), or use a paid plan with a
persistent disk mounted at `/data` (the image keeps everything there).
`KINTSUGI_DAILY_CALLS` in `render.yaml` caps model calls per day, so a loop cannot burn your free quota.

## 3. Any machine with Docker

```bash
docker build -t kintsugi .
docker run -p 8765:8765 \
  -e KINTSUGI_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -v kintsugi-data:/data kintsugi
```

Put it behind HTTPS (Caddy, nginx, a cloud load balancer, a tunnel). Set `KINTSUGI_TRUST_PROXY=1` only when a proxy
you control sets `X-Forwarded-For`.

## Settings (environment variables)

| Variable | Meaning |
|---|---|
| `KINTSUGI_TOKEN` | Access token. Required on a network address, 24+ characters. |
| `KINTSUGI_API_KEY`, `KINTSUGI_BASE_URL`, `KINTSUGI_MODEL` | Optional now: a model key set on the server. Most people add their own key in the app (Settings > Models) instead, which is saved in the keychain and (if you turn backups on) in your encrypted backup. |
| `KINTSUGI_PARALLEL` | Agents that may work at once (1-8, default 4; the app's Settings > Models can change it). |
| `KINTSUGI_DAILY_CALLS` | Model calls per day for the whole workspace (default 500, `0` = no cap). |
| `KINTSUGI_SANDBOX` | `auto` (default) or `require` (disable `run_python` when code cannot be isolated). |
| `KINTSUGI_BACKUP_REPO`, `KINTSUGI_BACKUP_TOKEN`, `KINTSUGI_BACKUP_PASSPHRASE`, `KINTSUGI_BACKUP_EVERY_MINUTES`, `KINTSUGI_BACKUP_PATH` | Encrypted backup to a private GitHub repo (see above). |
| `KINTSUGI_BACKUP_OVERWRITE=1`, `KINTSUGI_BACKUP_ACCEPT_OLD=1` | Only for emergencies: replace a newer or unreadable backup on purpose, or restore a backup that looks like an old copy put back (see "Backup safety checks"). |
| `KINTSUGI_WORKSPACE` | Where data lives (`/data` in the image). |
| `PORT`, `KINTSUGI_HOST` | Where to listen (`0.0.0.0` in the image). |

## Keeping your data on a free host: encrypted backup

The server saves one encrypted copy of your whole workspace (chats, agents, files, lessons, settings, secrets) to a
**private** GitHub repository, and restores it by itself when it starts on an empty disk.

1. On GitHub, create a **private** empty repository (for example `my-kintsugi-vault`).
2. Create a fine-grained token (Settings > Developer settings > Personal access tokens > Fine-grained): only that one
   repository, permission **Contents: Read and write**, nothing else.
3. On your hosting dashboard add three environment variables (secrets, never in the repository or a chat):
   `KINTSUGI_BACKUP_REPO` = `yourname/my-kintsugi-vault`, `KINTSUGI_BACKUP_TOKEN` = the token,
   `KINTSUGI_BACKUP_PASSPHRASE` = a long passphrase (12+ characters) that only you know.
4. Open Settings > Backup and press **Back up now**. After that it backs up by itself about every hour (`KINTSUGI_BACKUP_EVERY_MINUTES`,
   minimum 5) when something changed.

How it behaves, honestly:
- Encryption happens on the server before anything leaves it (PBKDF2-SHA256, 600,000 rounds, then authenticated AES via Fernet).
  GitHub only sees an opaque file. **If you lose the passphrase, the backup cannot be read by anyone.** Keep it somewhere safe.
- The backup refuses to run if the repository is public.
- A restore only happens when the workspace is empty (no agents, no messages). It never overwrites existing data. A wrong passphrase
  or a damaged file restores nothing and the log says why. You can also run `kintsugi workspace backup now|status|restore`.
- You lose at most the changes since the last backup (up to the interval) if the disk vanishes. The sign-in token is not
  part of the backup: it comes from `KINTSUGI_TOKEN`.
- Needs the optional package (`pip install "kintsugi[push]"`; the Docker image already has it). Limit: about 25 MB per backup.
- **Verified** against a fake GitHub server in tests; **not yet tried against the real api.github.com**.

## After it is running

- Open Details > Safety: it tells you whether agent code is isolated, where your messages are sent, and today's usage.
- Back up with Details > Safety > Download everything. Delete data any time from the same place.
- If you see "not isolated", the platform blocked the isolation tools; either accept that (you approve every run),
  or set `KINTSUGI_SANDBOX=require` so `run_python` stays off.


## Backup safety checks

Each backup carries a number and a time inside the encrypted file. Because of that:

- **A second copy cannot silently overwrite your backup.** If the backup in GitHub is newer than this workspace's last one (for example an old
  Render service you forgot is still running, or a fresh workspace pointed at a repository that already holds a real backup), the upload is
  refused and the Backup panel says so. Restore from it, or set `KINTSUGI_BACKUP_OVERWRITE=1` to replace it on purpose. A backup that cannot be
  read with the current passphrase is not overwritten either.
- **An old backup put back is noticed.** On an empty disk, a restore refuses a backup that GitHub shows as committed much more than 6 hours
  after the time written inside it (a sign someone put an older file in its place). Set `KINTSUGI_BACKUP_ACCEPT_OLD=1` to restore anyway.
- Limits: someone with write access to the backup repository *and* the passphrase can still do harm, and the date check relies on GitHub's
  commit dates. Backups made before this check existed carry no number and are accepted as before.
