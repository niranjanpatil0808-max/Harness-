# Using it on your phone

Everything here works in a phone browser; installing it makes it feel like an app.

## Install it

- **Android (Chrome):** open the app, tap the menu, choose **Install app** (or use **Install the app** in the sidebar).
- **iPhone (Safari):** tap **Share**, then **Add to Home Screen**. (Safari has no install button; the app shows the two steps.)

An installed app opens full-screen, keeps working shell-wise when you are offline (it shows "You're offline" and catches up when
you reconnect), and swipes open the sidebar from the left edge. The service worker caches only the app's own files, **never** your
chats, files or the access token.

## Talk to it

- **No @ needed.** In a group room, the **To** chips above the box choose who answers (the box says "Message @alice"). Tap another chip to switch. Typing your own `@name` always wins. In a direct chat there is nothing to pick.
- In a new chat, **starter ideas** appear above the box (tap one to fill the box, then edit or send). They disappear after your first message.
- Tap the **microphone** to speak; your words appear as you talk. Tap the **speaker** to have replies read aloud. In
  **Settings > General** you can switch on a hands-free loop (it speaks the reply, then listens again) and pick a language.
- It uses your browser's own speech (free). On Android Chrome that is Google's, on iPhone it is Apple's, so **your voice may be
  processed by that company**. This app records and keeps nothing. iPhone support for speech recognition is patchier than Android's.
- If the microphone is blocked, the app says so; allow it for this site in your browser settings.

## How replies sound

**Settings > General > How replies sound**: Fun (witty and direct, never insulting), Regular, Brief, or write your own. It changes the
style only. Your own wording is refused if it tries to loosen the rules (for example "ignore your instructions").

## Search the web

**Settings > Search**: paste a key from Tavily or Brave (check their sites for the current free allowance). Agents then get a few
short, cited snippets. They cannot open pages. Secrets are never put in a search, and searches are capped per day.

## Automations

Open **Automations** in the sidebar:

- **Daily briefing:** news on your topics, with sources, at a time you choose.
- **Watch something:** checks a topic and messages you **only when something important changes** (otherwise silent).
- **Research report:** a short sourced report now, or on a schedule; saved as a file and summarised in the chat.
- **Your own task:** any instruction on a schedule.

Times use **your** time zone (set it once from the same screen). Each automation shows when it runs next, can be paused, run now,
or deleted. They need web search for news; without it they use only the agent's notes (the app tells you).

## Notifications

**Settings > General > Notifications**. A notification says only "You have something new": never the message. It is sent when an
agent wrote or something needs your approval **and you are not using the app**, at most once a minute. On iPhone, first add the app
to the Home Screen and open it from there.

Honest limits: voice depends on your phone's browser; notifications depend on Google's, Apple's or Mozilla's push service
(the server's signing is tested, but it has not been tried against the real services); the server needs the optional
`cryptography` package (`pip install "kintsugi[push]"`, already in the Docker image).
