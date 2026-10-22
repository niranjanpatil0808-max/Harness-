# Plugins

Plugins add **skills** (instructions) and **web-API tools** to your agents. No plugin code runs on your server: a plugin can
only hand an agent some text, or let it call web addresses the plugin declared in advance.

Install them from **Settings > Plugins**: pick an example, enter a GitHub repository (`owner/repo`), or paste a `plugin.json`.
You always get a **preview** first (every skill's full text, every host, every secret, every tool). Installing approves exactly that
fingerprint; if the plugin changes in between, it refuses. A plugin does nothing for an agent until you switch it on for that
agent (Settings > Plugins, or the agent's Details).

## What a plugin file looks like

```json
{
  "id": "open-meteo",
  "name": "Weather (Open-Meteo)",
  "version": "1.0.0",
  "author": "you",
  "description": "Current weather by latitude and longitude.",
  "skills": [
    {"name": "weather-answers", "text": "Find the coordinates yourself, call open_meteo__now, answer in one sentence."}
  ],
  "tools": [
    {
      "name": "now",
      "description": "Current weather at a latitude/longitude",
      "method": "GET",
      "url": "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true",
      "hosts": ["api.open-meteo.com"],
      "params": {"lat": {"type": "number"}, "lon": {"type": "number"}}
    }
  ]
}
```

- **Skills**: `text` inline, or `"file": "skills/tip.md"` when the plugin comes from a GitHub repository. Up to 8 skills, 6,000 characters each.
- **Tools**: up to 8. The agent calls them as `<plugin_id>__<tool>` (dashes become underscores), for example `open_meteo__now`, so a
  plugin can never replace a built-in tool.
- **Parameters** are typed (`string`, `number`, `integer`, `boolean`), length-limited, may have an `enum`, and are put into the URL's
  path or query, URL-encoded. They can never change the host.
- **`method`** is `GET` or `POST`. A POST sends JSON made from the parameters listed in `"body"`, and **always waits for your approval**
  because it sends data out.
- **`auth`** (optional): `{"secret": "GITHUB_TOKEN", "header": "Authorization", "prefix": "Bearer "}`. The value comes from that agent's
  keychain by name (Details > Secrets), is sent only to the declared hosts, and never reaches the model or the logs.
- A repository plugin has its `plugin.json` at the top level; skill files are `.md`/`.txt` files up to 3 folders deep.
  To make plugins discoverable, give your repository the `dsh-plugin` topic (the convention DeepSeek Harness uses).

## How it stays safe

| Risk | What stops it |
|---|---|
| A plugin runs code on your server | There is no plugin code. The manifest is checked against a strict whitelist; unknown fields are refused. |
| A plugin reaches your internal network | Tools use the same guarded client as `web_fetch`: public addresses only, the connection is pinned to the checked address, https only, declared hosts only, no redirects for requests that carry a key. |
| A plugin steals a key | Keys are injected by name for the declared header only. A secret value in an argument is refused. |
| A plugin quietly goes online | Every plugin tool is internet use: the agent's **Off / Ask / Allow** applies, and writes always ask. |
| A plugin changes after you looked | You approve a fingerprint; there is no auto-update; a file changed on disk stops being trusted. |
| A plugin's skill tells the agent to misbehave | The skill is shown to you in full before install, and sits **below** the safety rules, approvals and permissions in the agent's prompt, which it cannot change. This is guidance to the model, not a hard guarantee: only install plugins you trust. |
| A tool's answer contains instructions | Results are labelled untrusted data; the agent is told never to follow instructions in them. Approvals still apply. |

Limits worth knowing: a malicious skill can still try to persuade a model (models can be fooled), so treat installing a plugin
like installing an app. Plugins are stored in the workspace `plugins/` folder, so they are included in the encrypted backup.
Python-code plugins (run inside the sandbox, with approval) are **not implemented yet**.

## Credit

The plugin idea (plugins contributing tools and skills; discovery through a GitHub topic) is taken from
[DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) (MIT). This implementation is written from scratch and is much
smaller: it has no plugin runtime.
