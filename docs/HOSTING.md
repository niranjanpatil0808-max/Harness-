# Running the workspace somewhere you can reach from a phone

Three ways, easiest first. All of them need **your own model API key** (for example a free Groq key) and a
**long random access token** that you choose. Never paste either into a chat, issue or the repository.

> Status: the package, the web page and the server were run in a clean environment exactly as the container runs
> them (see `SECURITY.md`). The Docker image and the Render blueprint have not been deployed by the author yet, so
> expect to fix a small thing on first deploy and tell us.

## 1. GitHub Codespaces (works from a phone browser)

1. Add secrets: GitHub > Settings > Codespaces > Secrets: `KINTSUGI_API_KEY` (your model key) and `KINTSUGI_TOKEN`
   (any random string of 24+ characters; mashing a keyboard for a while is fine, or use a password manager).
   Give them access to this repository.
2. Repository > Code > Codespaces > Create codespace. It installs the package, runs the tests and starts the server.
3. Open the forwarded port 8765 and sign in with your `KINTSUGI_TOKEN`. Keep the port **Private** (the default).
4. Codespaces sleep after inactivity; files persist until you delete the codespace.

## 2. Render (a public web address, free plan)

1. Push or fork this repository to your GitHub account.
2. render.com > New > Blueprint > pick the repository. Render reads `render.yaml`.
3. In the new service's Environment tab, paste your model key into `KINTSUGI_API_KEY`. `KINTSUGI_TOKEN` is generated
   for you; copy it from the same tab: that is your sign-in token.
4. Open the service address and sign in. The Safety tab shows how code is isolated.

Things to know about the **free plan**: the service sleeps when idle (the first visit after a while is slow and
scheduled jobs do not run while it sleeps), and **files are lost on every deploy or restart** (chats, agents,
lessons). For lasting data use a paid plan with a persistent disk mounted at `/data` (the image keeps everything there).
`KINTSUGI_DAILY_CALLS` in `render.yaml` caps model calls per day, so a loop cannot burn your free quota.

## 3. Any machine with Docker

```bash
docker build -t kintsugi .
docker run -p 8765:8765 \
  -e KINTSUGI_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  -e KINTSUGI_API_KEY=... -v kintsugi-data:/data kintsugi
```

Put it behind HTTPS (Caddy, nginx, a cloud load balancer, a tunnel). Set `KINTSUGI_TRUST_PROXY=1` only when a proxy
you control sets `X-Forwarded-For`.

## Settings (environment variables)

| Variable | Meaning |
|---|---|
| `KINTSUGI_TOKEN` | Access token. Required on a network address, 24+ characters. |
| `KINTSUGI_API_KEY`, `KINTSUGI_BASE_URL`, `KINTSUGI_MODEL` | Your model provider (defaults to Groq). |
| `KINTSUGI_DAILY_CALLS` | Model calls per day for the whole workspace (default 500, `0` = no cap). |
| `KINTSUGI_SANDBOX` | `auto` (default) or `require` (disable `run_python` when code cannot be isolated). |
| `KINTSUGI_WORKSPACE` | Where data lives (`/data` in the image). |
| `PORT`, `KINTSUGI_HOST` | Where to listen (`0.0.0.0` in the image). |

## After it is running

- Open Details > Safety: it tells you whether agent code is isolated, where your messages are sent, and today's usage.
- Back up with Details > Safety > Download everything. Delete data any time from the same place.
- If you see "not isolated", the platform blocked the isolation tools; either accept that (you approve every run),
  or set `KINTSUGI_SANDBOX=require` so `run_python` stays off.
