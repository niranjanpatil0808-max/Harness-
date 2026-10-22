"use strict";
/* Kintsugi UI, part 2: Settings page, usage dashboard, first-run setup, quick switcher, starter teams.
   Loaded after app.js and uses its helpers (h, api, dialog, S, ...). No build step. */

/* ---------- settings: a proper page with grouped sections ---------- */
const SETTINGS_GROUPS = [["You", ["general"]], ["AI", ["models", "usage"]], ["Team", ["team"]], ["Connections", ["internet", "integrations", "plugins", "search"]], ["Safety and data", ["improve", "backup"]]];
if (!SETTINGS_TAB_LIST.some((t) => t[0] === "usage")) SETTINGS_TAB_LIST.push(["usage", "Usage", "admin"]);
SETTINGS_PANELS.usage = () => usagePanel();
const SETTINGS_BLURB = {general: "Your account, voice, reply style and notifications", models: "Your AI providers and API keys", usage: "What the AI has used, and what it cost", team: "People, roles and approvals",
  internet: "Whether agents may go online", integrations: "GitHub, Slack, Calendar, Gmail", plugins: "Add skills and tools", search: "Web search key", improve: "Let the workspace tune its agents", backup: "Keep your data safe"};

settingsDialog = async function settingsDialog(tab) {
  if (typeof tab !== "string") tab = S.settingsTab || "general";
  closeSidebarMobile();
  const allowed = settingsTabs(); if (!allowed.some((t) => t[0] === tab)) tab = "general";
  S.settingsOpen = true;
  const labels = Object.fromEntries(allowed), body = h("div", {id: "settings-body", class: "set-body"}), nav = h("nav", {class: "set-nav", "aria-label": "Settings sections"});
  const show = async (key) => {
    S.settingsTab = key;
    fill(nav, SETTINGS_GROUPS.map(([group, keys]) => { const mine = keys.filter((k) => labels[k]); return mine.length ? h("div", {class: "set-group"}, h("div", {class: "set-h"}, group),
      mine.map((k) => h("button", {class: "set-item" + (k === key ? " on" : ""), "aria-current": k === key ? "page" : null, onclick: () => show(k)}, labels[k]))) : null; }));
    const active = nav.querySelector(".set-item.on"); if (active && active.scrollIntoView) active.scrollIntoView({inline: "center", block: "nearest"});
    fill(body, h("h3", {class: "set-title"}, labels[key]), h("p", {class: "muted", style: "margin:-6px 0 14px"}, SETTINGS_BLURB[key] || ""), h("p", {class: "muted"}, "Loading…"));
    try { const panel = await SETTINGS_PANELS[key](); fill(body, h("h3", {class: "set-title"}, labels[key]), h("p", {class: "muted", style: "margin:-6px 0 14px"}, SETTINGS_BLURB[key] || ""), h("div", {id: "set-panel"}, panel)); }
    catch (e) { fill(body, h("p", {class: "muted"}, e.message)); }
    if (key === "improve") renderImproveSections(S.improve);
    body.scrollTop = 0;
  };
  const close = dialog("Settings", null, h("div", {class: "set-grid"}, nav, body), (c) => [h("button", {class: "btn primary", onclick: c}, "Done")], () => { S.settingsOpen = false; });
  close.dialog.classList.add("settings");
  await show(tab);
};
// the panels refresh themselves by replacing #settings-body: keep that working with the new heading
const _fillRef = fill;
fill = function (el, ...kids) {
  if (el && el.id === "settings-body" && !(kids.flat(Infinity).some((k) => k && k.nodeType && k.className === "set-title"))) {
    const key = S.settingsTab, label = (settingsTabs().find((t) => t[0] === key) || [])[1] || "";
    return _fillRef(el, h("h3", {class: "set-title"}, label), h("p", {class: "muted", style: "margin:-6px 0 14px"}, SETTINGS_BLURB[key] || ""), h("div", {id: "set-panel"}, ...kids));
  }
  return _fillRef(el, ...kids);
};

/* ---------- usage dashboard ---------- */
async function usagePanel() {
  const d = await api("/api/usage?days=14");
  const total = d.days.reduce((a, x) => a + x.calls, 0), tokens = d.days.reduce((a, x) => a + x.prompt_tokens + x.completion_tokens, 0), cost = d.days.reduce((a, x) => a + x.cost, 0), allPriced = d.days.every((x) => x.priced);
  const max = Math.max(1, ...d.days.map((x) => x.calls));
  const fmt = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
  const stat = (label, value, sub) => h("div", {class: "stat"}, h("div", {class: "stat-v"}, value), h("div", {class: "stat-l"}, label), sub ? h("div", {class: "muted", style: "font-size:12px"}, sub) : null);
  const bars = d.days.length ? h("div", {class: "bars", role: "img", "aria-label": "Model calls per day: " + d.days.map((x) => x.name + " " + x.calls).join(", ")},
    d.days.map((x) => h("div", {class: "bar", title: x.name + ": " + x.calls + " calls"}, h("div", {class: "bar-fill", style: "height:" + Math.max(4, Math.round(x.calls / max * 100)) + "%"}), h("div", {class: "bar-l"}, x.name.slice(5))))) : h("p", {class: "muted"}, "Nothing yet. Usage appears here after the first reply.");
  const table = (title, rows) => rows.length ? h("div", {}, h("h4", {style: "margin:16px 0 6px"}, title), h("div", {class: "tbl"}, h("div", {class: "tr th"}, h("span", {}, "Name"), h("span", {}, "Calls"), h("span", {}, "Tokens"), h("span", {}, "Cost")),
    rows.map((r) => h("div", {class: "tr"}, h("span", {}, r.name), h("span", {}, r.calls), h("span", {}, d.tokens_known ? fmt(r.prompt_tokens + r.completion_tokens) : "n/a"), h("span", {}, r.priced ? "$" + r.cost.toFixed(4) : "n/a"))))) : null;
  const model = h("input", {type: "text", placeholder: "model name", "aria-label": "Model", autocapitalize: "none", list: "model-names"}), pin = h("input", {type: "number", min: 0, step: "any", placeholder: "$ per 1M input", "aria-label": "Price per million input tokens"}), pout = h("input", {type: "number", min: 0, step: "any", placeholder: "$ per 1M output", "aria-label": "Price per million output tokens"});
  return h("div", {}, h("div", {class: "stats"}, stat("Calls today", d.today_calls, d.daily_limit ? "of " + d.daily_limit + " allowed" : "no daily limit"), stat("Calls, 14 days", total), stat("Tokens, 14 days", d.tokens_known ? fmt(tokens) : "n/a", d.tokens_known ? "" : "your provider did not report them"),
    stat("Estimated cost", allPriced && total ? "$" + cost.toFixed(2) : "n/a", allPriced ? "from the prices you set" : "set prices below")),
    h("h4", {style: "margin:16px 0 6px"}, "Model calls per day"), bars, table("By agent", d.by_agent), table("By model", d.by_model),
    isOwner() ? h("div", {}, h("h4", {style: "margin:18px 0 6px"}, "Prices (for the cost estimate)"), h("p", {class: "muted", style: "font-size:13px;margin:0 0 8px"}, "Look up your provider's current price per million tokens and enter it. The estimate is only as good as these numbers."),
      h("datalist", {id: "model-names"}, d.by_model.map((m) => h("option", {value: m.name}))), h("div", {class: "price-row"}, model, pin, pout,
        h("button", {class: "btn", onclick: async () => { if (await act(() => api("/api/usage/price", {model: model.value.trim(), in: +pin.value, out: +pout.value}), "Price saved")) fill($("#settings-body"), await usagePanel()); }}, "Save price")),
      Object.keys(d.prices).length ? h("p", {class: "muted", style: "font-size:13px"}, "Saved: " + Object.entries(d.prices).map(([m, p]) => m + " ($" + p[0] + " in / $" + p[1] + " out)").join("; ")) : null) : null,
    isOwner() ? h("label", {class: "card", style: "display:flex;gap:10px;align-items:flex-start;font-weight:400;margin-top:16px"},
      h("input", {type: "checkbox", checked: d.summaries, style: "width:auto;margin-top:3px", "aria-label": "Summarize long chats", onchange: (e) => act(() => api("/api/compaction", {enabled: e.target.checked}), e.target.checked ? "Long chats will be summarized" : "Summaries off and deleted")}),
      h("span", {}, h("strong", {}, "Remember long chats"), h("br"), h("span", {class: "muted", style: "font-size:13px"}, "Agents see the last 12 messages. With this on, every 16 older messages are folded into a short summary they also see. Costs about one extra model call per 16 messages."))) : null,
    h("p", {class: "muted", style: "font-size:13px;margin-top:16px"}, "Numbers come from this workspace's own records and from what your provider reports. Your provider's dashboard is the final word on billing."));
}

/* ---------- first-run setup ---------- */
const WIZARD_HINTS = {groq: "Free tier, fast", openai: "GPT models", anthropic: "Claude models", gemini: "Gemini models", deepseek: "Low cost", openrouter: "Many models, one key", together: "Open models", ollama: "On your own computer, no key"};
const WIZARD_ORDER = ["groq", "openai", "anthropic", "gemini", "deepseek", "openrouter", "together", "ollama"];
async function setupWizard() {
  if (S.wizardOpen) return;
  S.wizardOpen = true;
  let providers, templates;
  try { providers = await api("/api/providers"); templates = await api("/api/templates"); } catch (e) { S.wizardOpen = false; return; }
  const box = h("div", {class: "wizard"});
  const finish = (close) => { S.wizardOpen = false; close(); };
  let closeFn;
  const dots = (n) => h("div", {class: "steps", "aria-label": "Step " + n + " of 3"}, [1, 2, 3].map((i) => h("span", {class: "dot2" + (i <= n ? " on" : "")})));
  const stepProvider = () => fill(box, dots(1), h("h3", {style: "margin:6px 0"}, "Welcome. Let's connect your AI."), h("p", {class: "muted", style: "margin:0 0 12px"}, "This app uses your own API key, so you stay in control of cost and data. Pick a provider."),
    h("div", {class: "pgrid"}, WIZARD_ORDER.filter((k) => providers.presets[k]).map((k) => h("button", {class: "pcard", onclick: () => stepKey(k)}, h("strong", {}, providers.presets[k].label.replace(/ \(.*\)/, "")), h("span", {class: "muted"}, WIZARD_HINTS[k] || "")))),
    h("div", {style: "margin-top:12px;display:flex;gap:8px;flex-wrap:wrap"}, h("button", {class: "btn", onclick: () => { finish(closeFn); settingsDialog("models"); }}, "Another provider or address"), h("button", {class: "btn", onclick: () => finish(closeFn)}, "Skip for now")));
  const stepKey = (id) => {
    const p = providers.presets[id], key = h("input", {type: "password", autocomplete: "off", "aria-label": "API key", placeholder: p.keyless ? "No key needed" : "Paste your API key"}), model = h("input", {type: "text", autocapitalize: "none", "aria-label": "Model name", value: p.model || "", placeholder: "model name"});
    const out = h("div", {class: "card", hidden: true}), go = h("button", {class: "btn primary"}, "Test and continue");
    key.disabled = !!p.keyless;
    go.onclick = async () => {
      out.hidden = false; out.textContent = "Testing…"; go.disabled = true;
      try {
        await api("/api/providers/save", {id, label: p.label, kind: p.kind, base_url: p.base_url, model: model.value.trim(), key: key.value, keyless: !!p.keyless, make_default: true});
        const r = await api("/api/providers/test", {id, model: model.value.trim() || undefined});
        if (r.ok) { out.textContent = "It works." + (r.reply ? " The model replied: " + r.reply : ""); setTimeout(stepTeam, 700); return; }
        fill(out, "That did not work: " + r.error + (r.models && r.models.length ? " Models your key can use: " + r.models.slice(0, 12).join(", ") : ""));
      } catch (e) { fill(out, e.message); }
      go.disabled = false; model.focus();
    };
    fill(box, dots(2), h("h3", {style: "margin:6px 0"}, p.label.replace(/ \(.*\)/, "")), p.signup ? h("p", {class: "muted", style: "margin:0 0 10px"}, "Get a key at ", h("a", {href: p.signup, target: "_blank", rel: "noopener"}, p.signup.replace("https://", "")), ". It is stored in your keychain, never shown again, and only sent to this provider.") : null,
      h("label", {}, "API key"), key, h("label", {style: "margin-top:10px"}, "Model"), model, h("small", {class: "muted"}, "A suggestion. If it fails, the error lists the models your key can use."), out,
      h("div", {style: "margin-top:12px;display:flex;gap:8px"}, h("button", {class: "btn", onclick: stepProvider}, "Back"), go));
    setTimeout(() => (p.keyless ? model : key).focus(), 50);
  };
  const stepTeam = () => fill(box, dots(3), h("h3", {style: "margin:6px 0"}, "Pick a starter team"), h("p", {class: "muted", style: "margin:0 0 12px"}, "Ready-made agents so you can start talking right away. You can change or delete them any time."),
    h("div", {class: "pgrid"}, templates.map((t) => h("button", {class: "pcard", onclick: async () => { try { const r = await api("/api/templates/apply", {id: t.id}); finish(closeFn); await poll(true); if (r.room) openRoom(r.room); toast("Your team is ready. Say hello!"); } catch (e) { toast(e.message, true); } }}, h("strong", {}, t.title), h("span", {class: "muted"}, t.description)))),
    h("div", {style: "margin-top:12px"}, h("button", {class: "btn", onclick: () => finish(closeFn)}, "Skip, I will add agents myself")));
  stepProvider();
  closeFn = dialog("Set up", null, box, null, () => { S.wizardOpen = false; });
  closeFn.dialog.classList.add("wizard-dialog");
}
function noModelNotice() {
  if (S.noModelShown) return; S.noModelShown = true;
  dialog("This workspace needs an AI model", "The owner has not connected an AI provider yet, so agents cannot answer. Ask the owner to open Settings and add their API key.", h("div", {}), (c) => [h("button", {class: "btn primary", onclick: c}, "OK")]);
}

/* ---------- starter teams (for admins, any time) ---------- */
async function startersDialog() {
  let templates; try { templates = await api("/api/templates"); } catch (e) { toast(e.message, true); return; }
  const close = dialog("Start from a team", "Adds ready-made agents and a shared room. Nothing is deleted.", h("div", {class: "pgrid"}, templates.map((t) => h("button", {class: "pcard", onclick: async () => {
    try { const r = await api("/api/templates/apply", {id: t.id}); close(); await poll(true); if (r.room) openRoom(r.room); toast(r.agents.length ? "Added " + r.agents.join(", ") : "Those agents already exist"); } catch (e) { toast(e.message, true); } }},
    h("strong", {}, t.title), h("span", {class: "muted"}, t.description), h("small", {class: "muted"}, t.agents.join(", "))))), (c) => [h("button", {class: "btn", onclick: c}, "Close")]);
}

/* ---------- quick switcher: chats, settings and message search ---------- */
function openSwitcher() {
  if ($("#dialog-root .switcher")) return;
  const input = h("input", {type: "text", class: "sw-input", placeholder: "Search chats, agents, settings and messages", "aria-label": "Search", autocomplete: "off", role: "combobox", "aria-expanded": "true", "aria-controls": "sw-list"});
  const list = h("div", {class: "sw-list", id: "sw-list", role: "listbox"});
  let items = [], idx = 0, timer = 0, token = 0, close;
  const go = (it) => { close(); it.run(); };
  const draw = () => fill(list, items.length ? items.map((it, i) => h("button", {class: "sw-item" + (i === idx ? " on" : ""), role: "option", "aria-selected": i === idx, onclick: () => go(it), onmousemove: () => { if (idx !== i) { idx = i; draw(); } }},
    h("span", {class: "sw-kind"}, it.kind), h("span", {class: "sw-t"}, it.title), it.sub ? h("span", {class: "sw-sub"}, it.sub) : null)) : h("p", {class: "muted", style: "padding:10px"}, input.value.trim().length < 2 ? "Type to search." : "No matches."));
  const local = (q) => {
    const out = [], low = q.toLowerCase();
    for (const r of rooms()) { const label = roomLabel(r); if (!low || label.toLowerCase().includes(low)) out.push({kind: r.kind === "dm" ? "Chat" : "Room", title: (r.kind === "dm" ? "" : "# ") + label, run: () => openRoom(r.name)}); }
    for (const a of agents()) if (!low || a.name.includes(low)) out.push({kind: "Agent", title: a.name, sub: a.persona.slice(0, 60), run: () => dmWith(a.name)});
    for (const [k, label] of settingsTabs()) if (!low || label.toLowerCase().includes(low) || k.includes(low)) out.push({kind: "Settings", title: label, sub: SETTINGS_BLURB[k], run: () => settingsDialog(k)});
    if (S.room && (!low || "save export download chat markdown".includes(low) || low.split(" ").some((w) => w.length > 2 && "save export download markdown".includes(w)))) out.push({kind: "Action", title: "Save this chat as a file", run: () => exportChat(S.room)});
    if (isAdmin() && (!low || "starter team template".includes(low))) out.push({kind: "Action", title: "Start from a team", run: startersDialog});
    return out.slice(0, 14);
  };
  const search = async () => {
    const q = input.value.trim(); items = local(q); idx = 0; draw();
    if (q.length < 2) return;
    const mine = ++token;
    try {
      const found = await api("/api/find?q=" + encodeURIComponent(q));
      if (mine !== token) return;
      const labelOf = (name) => { const r = rooms().find((x) => x.name === name); return r ? (r.kind === "dm" ? roomLabel(r) : "# " + r.name) : name; };
      items = items.concat(found.map((m) => ({kind: "Message", title: m.snippet, sub: labelOf(m.room) + " · " + m.sender, run: () => openRoom(m.room)})));
      draw();
    } catch (e) { /* the local results stay */ }
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 200); items = local(input.value.trim()); idx = 0; draw(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(items.length - 1, idx + 1); draw(); list.querySelector(".on")?.scrollIntoView({block: "nearest"}); }
    else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(0, idx - 1); draw(); list.querySelector(".on")?.scrollIntoView({block: "nearest"}); }
    else if (e.key === "Enter" && items[idx]) { e.preventDefault(); go(items[idx]); }
  });
  items = local(""); draw();
  close = dialog("Search", null, h("div", {class: "switcher"}, input, list), null);
  close.dialog.classList.add("switcher-dialog");
  input.focus();
}
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (S.state && !$("#dialog-root .dialog:not(.switcher-dialog)")) openSwitcher(); }
});

/* new-chat dialog gets a starter-teams shortcut for admins */
const _newChatDialog = newChatDialog;
newChatDialog = function () {
  _newChatDialog();
  if (isAdmin()) { const d = $("#dialog-root .dialog:last-child .actions"); if (d) d.prepend(h("button", {class: "btn", onclick: () => { $("#dialog-root").replaceChildren(); $("#app").inert = false; startersDialog(); }}, "Start from a team")); }
};

/* ---------- save a chat as a Markdown file (uses the same access checks as reading it) ---------- */
async function exportChat(room) {
  try {
    const all = []; let after = 0;
    for (let page = 0; page < 250; page++) {  // 200 a page, oldest first; stops at 50,000 messages
      const got = await api("/api/messages?order=asc&room=" + encodeURIComponent(room) + "&after=" + after);
      all.push(...got); if (got.length < 200) break; after = got[got.length - 1].id;
    }
    const r = rooms().find((x) => x.name === room), title = r ? (r.kind === "dm" ? "Chat with " + roomLabel(r) : "#" + room) : room;
    const md = "# " + title + "\n\n" + all.map((m) => "**" + m.sender + "** · " + new Date(m.ts * 1000).toLocaleString() + "\n\n" + m.text + "\n").join("\n---\n\n");
    const a = h("a", {href: URL.createObjectURL(new Blob([md], {type: "text/markdown"})), download: (title.replace(/[^\w-]+/g, "-").replace(/^-|-$/g, "") || "chat") + ".md"});
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    toast("Saved " + all.length + " messages");
  } catch (e) { toast(e.message, true); }
}
