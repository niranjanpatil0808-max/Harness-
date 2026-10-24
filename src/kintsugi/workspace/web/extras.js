"use strict";
/* Kintsugi UI, part 2: Settings page, usage dashboard, first-run setup, quick switcher, starter teams.
   Loaded after app.js and uses its helpers (h, api, dialog, S, ...). No build step. */

/* ---------- settings: a proper page with grouped sections ---------- */
const SETTINGS_GROUPS = [["You", ["general"]], ["AI", ["models", "usage"]], ["Team", ["team"]], ["Connections", ["internet", "integrations", "plugins", "search"]], ["Safety and data", ["improve", "approvals", "backup"]]];
if (!SETTINGS_TAB_LIST.some((t) => t[0] === "usage")) SETTINGS_TAB_LIST.push(["usage", "Usage", "admin"]);
SETTINGS_PANELS.usage = () => usagePanel();
if (!SETTINGS_TAB_LIST.some((t) => t[0] === "approvals")) SETTINGS_TAB_LIST.push(["approvals", "Remembered approvals", "owner"]);
SETTINGS_PANELS.approvals = () => approvalsPanel();
const SETTINGS_BLURB = {general: "Your account, voice, reply style and notifications", models: "Your AI providers and API keys", usage: "What the AI has used, and what it cost", team: "People, roles and approvals",
  internet: "Whether agents may go online", integrations: "GitHub, Slack, Calendar, Gmail", plugins: "Add skills and tools", search: "Web search key", improve: "Let the workspace tune its agents", approvals: "Actions you chose to always allow", backup: "Keep your data safe"};

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
const WIZARD_HINTS = {groq: "Free tier, fast", meta: "Meta Llama models", openai: "GPT models", anthropic: "Claude models", gemini: "Gemini models", deepseek: "Low cost", openrouter: "Many models, one key", together: "Open models", ollama: "On your own computer, no key"};
const WIZARD_ORDER = ["groq", "meta", "openai", "anthropic", "gemini", "deepseek", "openrouter", "together", "ollama"];
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
    if (!low || "tasks team board assign".includes(low) || low.split(" ").some((w) => w.length > 2 && "tasks board assign".includes(w))) out.push({kind: "Action", title: "Team tasks", sub: "Give an agent a task, follow progress", run: () => tasksDialog()});
    if (!low || "help guide how to use tips".includes(low) || low.split(" ").some((w) => w.length > 2 && "help guide tips tour".includes(w))) out.push({kind: "Action", title: "How to use Kintsugi", run: helpDialog});
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

/* ---------- team task board: give an agent a task in a shared room, and everyone in that room can follow it ---------- */
const TASK_LABEL = {queued: "Waiting to start", working: "Working", waiting: "Needs approval", done: "Done", stopped: "Stopped", failed: "Failed"};
async function tasksDialog(room) {
  let list = [], timer = 0, closed = false;
  const mine = () => rooms().filter((r) => r.members.includes(me().name) && roomAgents(r).length);
  const roomSel = h("select", {"aria-label": "Room"}, mine().map((r) => h("option", {value: r.name, selected: r.name === (room || S.room)}, r.kind === "dm" ? "Private: " + roomLabel(r) : "#" + r.name)));
  const agentSel = h("select", {"aria-label": "Agent"});
  const fillAgents = () => { const r = rooms().find((x) => x.name === roomSel.value); fill(agentSel, (r ? roomAgents(r) : []).map((a) => h("option", {value: a}, a))); };
  roomSel.onchange = fillAgents; fillAgents();
  const repeat = h("select", {"aria-label": "Repeat"}, [["", "Just once"], ["weekdays", "Repeat every weekday at 9:00"], ["weekly", "Repeat every Monday at 9:00"], ["daily", "Repeat every day at 9:00"]].map(([v, l]) => h("option", {value: v}, l)));
  const what = h("textarea", {rows: 2, placeholder: "What should the agent do? e.g. Draft the launch email for Friday", "aria-label": "Task", maxlength: 600});
  const give = h("button", {class: "btn primary"}, "Give task");
  give.onclick = async () => {
    if (!what.value.trim()) { what.focus(); return; }
    give.disabled = true;
    try { await api("/api/tasks/create", {room: roomSel.value, agent: agentSel.value, title: what.value, repeat: repeat.value}); if (repeat.value) toast("It will also repeat. See Automations to change that."); what.value = ""; toast("Task given. Everyone in the room can follow it here."); S.fast = 12; await refresh(); }
    catch (e) { toast(e.message, true); }
    give.disabled = false;
  };
  const board = h("div", {class: "task-board", "aria-live": "polite"});
  const card = (t) => {
    const r = rooms().find((x) => x.name === t.room), where = r ? (r.kind === "dm" ? "private chat" : "#" + t.room) : t.room;
    const canChange = t.created_by === me().name || isAdmin(), open = ["queued", "working", "waiting"].includes(t.status);
    return h("div", {class: "task-card st-" + t.status},
      h("div", {class: "task-top"}, h("span", {class: "task-chip st-" + t.status}, TASK_LABEL[t.status] || t.status), h("span", {class: "muted", style: "font-size:12px"}, "#" + t.id + " · " + clock(t.updated))),
      h("div", {class: "task-title"}, t.title),
      h("div", {class: "muted", style: "font-size:13px"}, avatar(t.agent), " " + t.agent + " · " + where + " · given by " + t.created_by),
      h("div", {class: "task-actions"},
        r ? h("button", {class: "btn", onclick: () => { close(); openRoom(t.room); if (t.result_id || t.message_id) setTimeout(() => jumpTo(t.result_id || t.message_id), 400); }}, t.result_id ? "See the result" : "Open the chat") : null,
        canChange && !open ? h("button", {class: "btn", onclick: () => change(t, "retry", "Asked again")}, "Ask again") : null,
        canChange && open ? h("button", {class: "btn", onclick: () => change(t, "done", "Marked done")}, "Mark done") : null,
        canChange ? h("button", {class: "btn danger", "aria-label": "Remove task " + t.id, onclick: () => change(t, "delete", "Removed")}, "Remove") : null));
  };
  const change = async (t, action, ok) => { try { await api("/api/tasks/update", {id: t.id, action}); toast(ok); await refresh(); } catch (e) { toast(e.message, true); } };
  const draw = () => {
    const active = list.filter((t) => ["queued", "working", "waiting"].includes(t.status)), past = list.filter((t) => !active.includes(t));
    fill(board, list.length ? [active.length ? [h("h4", {}, "In progress (" + active.length + ")"), active.map(card)] : null, past.length ? [h("h4", {}, "Finished"), past.slice(0, 60).map(card)] : null]
      : h("div", {class: "hello", style: "padding:20px 0"}, h("p", {}, "No tasks yet. Give an agent a task above: it works on it in the room, and everyone there sees how it is going.")));
  };
  const refresh = async () => { try { list = await api("/api/tasks"); draw(); } catch (e) { /* the poll reports connection problems */ } };
  const tick = async () => { if (closed) return; await refresh(); timer = setTimeout(tick, 3000); };
  const form = mine().length ? h("div", {class: "task-form"}, h("div", {class: "task-row"}, roomSel, agentSel), what, repeat, give)
    : h("p", {class: "muted"}, isAdmin() ? "Add an agent to a room first (New agent, or Start from a team)." : "You are not in a room with an agent yet. Ask an admin to add you.");
  what.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); give.click(); } });
  const close = dialog("Team tasks", "Hand work to an agent in a room or private chat. Everyone in that room can follow it.", h("div", {}, form, board), (c) => [h("button", {class: "btn primary", onclick: c}, "Done")], () => { closed = true; clearTimeout(timer); });
  close.dialog.classList.add("tasks-dialog");
  draw(); tick();
}
function jumpTo(id) { const el = document.querySelector('[data-mid="' + id + '"]'); if (el) { el.scrollIntoView({block: "center"}); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1600); } }

/* ---------- share an answer into a room ---------- */
function shareDialog(m) {
  const targets = rooms().filter((r) => r.kind !== "dm" && r.name !== m.room && r.members.includes(me().name));
  if (!targets.length) { toast("You are not in any other room to share into", true); return; }
  const sel = h("select", {"aria-label": "Share to room"}, targets.map((r) => h("option", {value: r.name}, "#" + r.name)));
  const close = dialog("Share this message", "It is copied into the room with your name and where it came from. Nobody is woken up by it.", h("div", {}, h("blockquote", {class: "share-preview"}, m.text.slice(0, 400) + (m.text.length > 400 ? "…" : "")), sel),
    (c) => [h("button", {class: "btn", onclick: c}, "Cancel"), h("button", {class: "btn primary", onclick: async () => { try { await api("/api/share", {id: m.id, room: sel.value}); c(); toast("Shared to #" + sel.value); } catch (e) { toast(e.message, true); } }}, "Share")]);
}

/* ---------- personalisation: what agents have learned about you (yours only; edit, clear or switch off) ---------- */
const _generalPanel = SETTINGS_PANELS.general;
SETTINGS_PANELS.general = async () => {
  const base = await _generalPanel();
  let p; try { p = await api("/api/me/profile"); } catch (e) { return base; }
  const style = h("textarea", {rows: 3, maxlength: 600, "aria-label": "How you like replies", placeholder: "Nothing learned yet. It fills in as you chat, or write it yourself, e.g. Short answers with bullet points."}, p.style);
  const context = h("textarea", {rows: 3, maxlength: 600, "aria-label": "About your work", placeholder: "e.g. I run growth at a small startup and write weekly updates."}, p.context);
  const on = h("input", {type: "checkbox", checked: p.enabled, style: "width:auto", "aria-label": "Learn from my chats",
    onchange: (e) => act(() => api("/api/me/profile/save", {action: "enabled", enabled: e.target.checked}), e.target.checked ? "Agents will keep learning how you like to work" : "Learning is off; agents will not use your profile")});
  const refresh = async () => fill($("#settings-body"), await SETTINGS_PANELS.general());
  const section = h("div", {class: "card", id: "personal", style: "margin-top:18px"},
    h("h4", {style: "margin:0 0 4px"}, "What agents have learned about you"),
    h("p", {class: "muted", style: "font-size:13px;margin:0 0 10px"}, "Every few messages, agents update this from what you write and the replies you mark 👍 or 👎. Only you see it here. " +
      (p.learned ? "Updated " + p.learned + " time" + (p.learned === 1 ? "" : "s") + (p.updated ? ", last on " + new Date(p.updated * 1000).toLocaleDateString() : "") + "." : "Nothing learned yet.")),
    h("label", {style: "display:flex;gap:8px;align-items:center;font-weight:400;margin-bottom:10px"}, on, "Learn from my chats and use it in replies"),
    h("label", {}, "How you like replies"), style, h("small", {class: "muted", style: "display:block;margin:2px 0 10px"}, "Used in every chat with you."),
    h("label", {}, "About your work"), context, h("small", {class: "muted", style: "display:block;margin:2px 0 10px"}, "Used only in your private chats with agents, never in shared rooms."),
    h("div", {style: "display:flex;gap:8px;flex-wrap:wrap"},
      h("button", {class: "btn primary", onclick: async () => { const r = await act(() => api("/api/me/profile/save", {style: style.value, context: context.value}), "Saved"); if (r && (r.style !== style.value.trim() || r.context !== context.value.trim())) toast("Saved. Anything that looked like a rule change or a secret was left out."); await refresh(); }}, "Save"),
      h("button", {class: "btn danger", onclick: () => confirmDialog("Clear what agents learned about you?", "They start learning again from your next messages (unless you switch learning off).", "Clear", async () => { await act(() => api("/api/me/profile/save", {action: "clear"}), "Cleared"); await refresh(); })}, "Clear")),
    h("p", {class: "muted", style: "font-size:12px;margin:10px 0 0"}, "It only shapes style and context: it can never change what agents are allowed to do. Each update is one extra model call (about one per " + 8 + " of your messages). Health, money, passwords and other secrets are never kept on purpose; check it now and then and edit what is wrong."));
  section.style.marginTop = "0"; section.style.marginBottom = "18px";
  return h("div", {}, section, base);
};

/* rate an agent's reply: it teaches agents what works for you */
async function rate(m, good, btn) {
  S.rated = S.rated || {};
  const now = S.rated[m.id] === good ? null : good;
  try {
    await api("/api/feedback", {id: m.id, good: now});
    S.rated[m.id] = now;
    const row = btn.closest(".msg-actions"); if (row) row.querySelectorAll(".rate").forEach((b) => b.classList.toggle("on", S.rated[m.id] === (b.dataset.good === "1")));
    if (now !== null) toast(now ? "Thanks. Agents will do more of this for you." : "Noted. Agents will adjust to you over time.");
  } catch (e) { toast(e.message, true); }
}


/* ---------- a short guide inside the app ---------- */
function helpDialog() {
  const tip = (title, text) => h("div", {class: "tip"}, h("strong", {}, title), h("p", {class: "muted", style: "margin:2px 0 0"}, text));
  const touch = matchMedia("(hover: none)").matches;
  dialog("How to use Kintsugi", "A few things worth knowing.", h("div", {class: "tips"},
    tip("Talk to an agent", "Type your message. In a group room, tap the @name chips above the box to choose who answers, or write @name yourself. @all asks every agent at once."),
    tip("Give a task to the team", "Tasks in the sidebar: pick a room and an agent and say what to do. Everyone in the room follows it to done."),
    tip("Approvals", "When an agent wants to run code or do something risky, a card shows exactly what it will do. Read it, then Allow once or Deny."),
    tip("Share a good answer", "Tap Share under any message to copy it into another room. 👍 and 👎 teach agents how you like answers."),
    tip("Find anything", touch ? "Tap Search in the sidebar to find chats, agents, settings and old messages." : "Press Ctrl or Cmd + K, or use Search in the sidebar, to find chats, agents, settings and old messages."),
    tip("Add a file", "The paperclip gives an agent a text file (notes, CSV, code). Only this chat can see it."),
    tip("Talk instead of type", "The microphone dictates your message, and the speaker reads replies aloud (Settings > General has a hands-free mode)."),
    tip("Stay in control", "Settings > Models for your AI key, Usage for what it costs, and Internet for what each agent may look up. Agents never go online unless you allow it."),
    isOwner() ? tip("Bring your team", "Settings > Team > Create invite link. Each link works once; send it privately.") : null),
    (c) => [h("button", {class: "btn primary", onclick: c}, "Got it")]);
}

/* ---------- "Get started": a checklist for a new owner ---------- */
function onboardingSteps() {
  const o = (S.state && S.state.onboarding) || {};
  return [
    {done: S.state.model_ready !== false, title: "Connect your AI", text: "Paste your own API key so agents can answer.", go: "Open Models", run: () => settingsDialog("models")},
    {done: !!o.messaged, title: "Say hello to an agent", text: "Type a message. Try: @alice write a short todo list.", go: "Start typing", run: () => { const t = $("#msg"); if (t) { t.focus(); } closeSidebarMobile(); }},
    {done: !!o.tasked, title: "Give your team a task", text: "Hand an agent a job and follow it to done.", go: "Open Tasks", run: () => tasksDialog()},
    {done: !!o.invited, title: "Invite a teammate", text: "Each link works once, and each person gets their own login.", go: "Open Team", run: () => settingsDialog("team")},
    {done: IS_STANDALONE() || matchMedia("(hover: hover)").matches, title: "Put it on your home screen", text: "Android Chrome: menu, Install app. iPhone Safari: Share, Add to Home Screen.", go: null, run: null},
  ];
}
const onboardingProgress = () => { const st = onboardingSteps(); return [st.filter((x) => x.done).length, st.length]; };
const onboardingDone = () => !!store.get("kt-onboard-off") || onboardingProgress()[0] >= onboardingProgress()[1];
function onboardingDialog() {
  const steps = onboardingSteps(), [done, total] = onboardingProgress();
  const close = dialog("Get started", done + " of " + total + " done", h("div", {class: "checklist"}, steps.map((s) => h("div", {class: "check" + (s.done ? " done" : "")},
    h("span", {class: "tick", "aria-hidden": "true"}, s.done ? "✓" : ""), h("div", {style: "flex:1"}, h("strong", {}, s.title), h("p", {class: "muted", style: "margin:2px 0 0;font-size:13px"}, s.text)),
    !s.done && s.go ? h("button", {class: "btn", onclick: () => { close(); s.run(); }}, s.go) : null))),
    (c) => [h("button", {class: "btn", onclick: () => { store.set("kt-onboard-off", "1"); c(); renderSidebarNow(); toast("Hidden. Find it again in the ? guide."); }}, "Hide this"), h("button", {class: "btn primary", onclick: c}, "Close")]);
}
function renderSidebarNow() { try { S.sig.side = null; renderSidebar(); } catch (e) { /* the next poll redraws */ } }

/* ---------- delete a message ---------- */
function deleteMessage(m) {
  confirmDialog("Delete this message?", "It disappears for everyone in this chat. Messages other people already shared from it stay where they were shared.", "Delete", async () => {
    await act(() => api("/api/message/delete", {id: m.id}), "Deleted");
    S.last[S.room] = 0; const t = $("#thread"); if (t) t.replaceChildren(); S.loadedRooms[S.room] = false; await poll(true);
  });
}

/* ---------- "while you were away": one short summary after a long absence ---------- */
async function awayDigest() {
  let last = 0; try { last = +(localStorage.getItem("kt-lastseen") || 0); } catch (e) { /* no storage */ }
  const now = Date.now() / 1000;
  const remember = () => { try { localStorage.setItem("kt-lastseen", String(Date.now() / 1000)); } catch (e) { /* ok */ } };
  window.addEventListener("pagehide", remember); document.addEventListener("visibilitychange", () => { if (document.hidden) remember(); });
  if (!last || now - last < 20 * 60 || !S.state) { remember(); return; }
  try {
    const tasks = await api("/api/tasks");
    const finished = tasks.filter((t) => t.updated > last && ["done", "failed"].includes(t.status)), waiting = S.state.approvals.filter((a) => a.can_decide !== false);
    const unread = rooms().filter((r) => isUnread(r)).length;
    if (!finished.length && !waiting.length && !unread) { remember(); return; }
    const hours = Math.round((now - last) / 360) / 10, since = hours >= 24 ? Math.round(hours / 24) + " day(s)" : hours + " hour(s)";
    dialog("While you were away", "Since about " + since + " ago:", h("div", {class: "away"},
      finished.length ? h("p", {}, "✓ " + finished.length + " task" + (finished.length === 1 ? "" : "s") + " finished: " + finished.slice(0, 3).map((t) => t.title.slice(0, 40)).join("; ")) : null,
      waiting.length ? h("p", {}, "⏳ " + waiting.length + " waiting for your approval") : null,
      unread ? h("p", {}, "💬 " + unread + " chat" + (unread === 1 ? " has" : "s have") + " new messages") : null),
      (c) => [finished.length ? h("button", {class: "btn", onclick: () => { c(); tasksDialog(); }}, "See tasks") : null, h("button", {class: "btn primary", onclick: c}, "OK")]);
  } catch (e) { /* the summary is a nicety */ }
  remember();
}

/* ---------- Models panel: show answers as they are written ---------- */
const _modelsPanel = SETTINGS_PANELS.models;
SETTINGS_PANELS.models = async () => {
  const base = await _modelsPanel();
  let on = true; try { on = (await api("/api/usage?days=1")).streaming !== false; } catch (e) { /* keep the default */ }
  const box = h("label", {class: "card", style: "display:flex;gap:10px;align-items:flex-start;font-weight:400;margin-top:14px"},
    h("input", {type: "checkbox", checked: on, style: "width:auto;margin-top:3px", "aria-label": "Show answers as they are written",
      onchange: (e) => act(() => api("/api/streaming", {enabled: e.target.checked}), e.target.checked ? "Answers will appear as they are written" : "Answers will appear when finished")}),
    h("span", {}, h("strong", {}, "Show answers as they are written"), h("br"), h("span", {class: "muted", style: "font-size:13px"}, "You see the words appear while the AI is still answering. If your provider does not support it, the app quietly asks the normal way.")));
  return h("div", {}, base, box);
};

/* ---------- room brief: a pinned note every agent in the room reads ---------- */
function renderBrief() {
  const r = curRoom(); let strip = $("#brief-strip");
  if (!strip) { strip = h("div", {id: "brief-strip"}); $("#topbar").after(strip); }
  const brief = r && r.kind === "room" ? (r.brief || "") : "";
  const sig = (r ? r.name : "") + "|" + brief + "|" + isAdmin();
  if (strip.dataset.sig === sig) return;
  strip.dataset.sig = sig;
  if (!r || r.kind !== "room" || (!brief && !isAdmin())) { strip.hidden = true; fill(strip); return; }
  strip.hidden = false;
  const edit = isAdmin() ? h("button", {class: "mini", onclick: () => briefDialog(r)}, brief ? "Edit" : "Add a room brief") : null;
  fill(strip, brief ? [h("span", {class: "brief-text", title: brief}, "📌 " + brief.replace(/\s+/g, " ")), edit] : [h("span", {class: "muted"}, "📌 Tell the agents what this room is for."), edit]);
}
function briefDialog(r) {
  const box = h("textarea", {rows: 5, maxlength: 1500, "aria-label": "Room brief", placeholder: "e.g. This room plans the Friday launch. Keep answers short and list the next step at the end."}, r.brief || "");
  const close = dialog("Room brief for #" + r.name, "Everyone in the room sees it, and every agent here reads it before answering. It cannot change what agents are allowed to do.", box,
    (c) => [h("button", {class: "btn", onclick: c}, "Cancel"), h("button", {class: "btn primary", onclick: async () => {
      try { const out = await api("/api/room/brief", {room: r.name, text: box.value}); toast(out.brief ? "Room brief saved" : "Room brief removed"); c(); await poll(true); } catch (e) { toast(e.message, true); } }}, "Save")]);
}
const _renderTopbar = renderTopbar;
renderTopbar = function (force) { _renderTopbar(force); try { renderBrief(); } catch (e) { /* cosmetic */ } };

/* ---------- outbox: a message typed with no signal waits and goes out when the connection is back ---------- */
const OUTBOX_KEY = "kt-outbox", OUTBOX_MAX = 20, OUTBOX_TRIES = 8;
// Waiting messages belong to the person who wrote them: another account on this browser neither sees nor sends them.
function outbox() {
  let all = [];
  try { const v = JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]"); all = Array.isArray(v) ? v : []; } catch (e) { all = S.memOutbox || []; }
  return all.filter((x) => x && x.user === me().name).slice(0, OUTBOX_MAX);
}
function saveOutbox(mine) {
  let others = [];
  try { const v = JSON.parse(localStorage.getItem(OUTBOX_KEY) || "[]"); others = (Array.isArray(v) ? v : []).filter((x) => x && x.user !== me().name); } catch (e) { /* no storage */ }
  const all = others.concat(mine.slice(0, OUTBOX_MAX));
  try { localStorage.setItem(OUTBOX_KEY, JSON.stringify(all)); } catch (e) { S.memOutbox = all; }  // no storage: kept while this page stays open
  renderOutbox();
}
function queueOutbox(room, text, cid) {
  const list = outbox();
  if (list.length >= OUTBOX_MAX) { toast("Too many messages are waiting to be sent. Yours is back in the message box.", true); return false; }
  saveOutbox(list.concat([{id: Date.now() + Math.random(), user: me().name, room, text: text.slice(0, 8000), cid: cid || String(Date.now()), tries: 0}]));
  toast("No connection. Your message will be sent when you are back online.");
  return true;
}
function backToDraft(item, why) {  // never lose what someone wrote: a message that cannot be sent goes back into that chat's message box
  const key = "kt-draft-" + item.room, have = store.get(key) || "";
  store.set(key, have ? have + "\n" + item.text : item.text);
  if (item.room === S.room) { const ta = $("#msg"); if (ta) { ta.value = store.get(key); ta.dispatchEvent(new Event("input")); } }
  toast("A waiting message could not be sent (" + why + "). It is back in your message box.", true);
}
let flushing = false;
async function flushOutbox() {
  if (flushing || !navigator.onLine || !S.token) return;
  if (!outbox().length) return;
  flushing = true;
  try {
    for (const first of outbox()) {
      const item = outbox().find((x) => x.id === first.id);  // cancelled while this was running: skip it
      if (!item) continue;
      try { await api("/api/say", {room: item.room, text: item.text, cid: item.cid}); }
      catch (e) {
        const keep = isNetworkError(e) || e.status === 401 || e.status === 429 || e.status >= 500;  // not their fault: try again later
        if (keep && (item.tries || 0) + 1 < OUTBOX_TRIES) { saveOutbox(outbox().map((x) => x.id === item.id ? {...x, tries: (x.tries || 0) + 1} : x)); break; }
        saveOutbox(outbox().filter((x) => x.id !== item.id)); backToDraft(item, keep ? "the server kept refusing it" : e.message); continue;
      }
      saveOutbox(outbox().filter((x) => x.id !== item.id));
    }
  } finally { flushing = false; }
  if (!outbox().length) { S.fast = 12; poll(true); }
}
function renderOutbox() {
  let box = $("#outbox"); if (!box) { const inline = $("#inline"); if (!inline) return; box = h("div", {id: "outbox"}); inline.after(box); }
  const here = outbox().filter((x) => x.room === S.room);
  fill(box, here.map((x) => h("div", {class: "queued", role: "status"}, h("span", {}, "⏳ Waiting to send: " + x.text.slice(0, 120)),
    h("button", {class: "mini", onclick: () => saveOutbox(outbox().filter((y) => y.id !== x.id))}, "Cancel"))));
}
window.addEventListener("online", () => { flushOutbox(); });
const _renderInline = renderInline;
renderInline = function () { _renderInline(); try { renderOutbox(); } catch (e) { /* cosmetic */ } };

/* ---------- quick commands: type / in the message box ---------- */
const SLASH = [["/task", "Give the team a task", "/task draft the launch email"], ["/search", "Search chats and messages", "/search pricing"], ["/help", "How to use Kintsugi", "/help"], ["/brief", "Edit this room's brief (admins)", "/brief"]];
function runSlash(text) {
  const m = text.match(/^\/(\w+)\s*([\s\S]*)$/); if (!m) return false;
  const cmd = m[1].toLowerCase(), rest = m[2].trim(), r = curRoom();
  if (cmd === "help") { helpDialog(); return true; }
  if (cmd === "search") { openSwitcher(); const i = $("#dialog-root .sw-input"); if (i && rest) { i.value = rest; i.dispatchEvent(new Event("input")); } return true; }
  if (cmd === "brief") { if (r && r.kind === "room" && isAdmin()) briefDialog(r); else toast("Only admins can edit a room brief, in shared rooms", true); return true; }
  if (cmd === "task") {
    if (!rest) { tasksDialog(); return true; }
    const agent = r && (r.kind === "dm" ? roomAgents(r)[0] : recipient());
    if (!agent) { toast("Open a chat with an agent first", true); return true; }
    api("/api/tasks/create", {room: S.room, agent, title: rest}).then(() => { toast("Task given to " + agent); S.fast = 12; poll(true); }).catch((e) => { toast(e.message, true); const ta = $("#msg"); if (ta && !ta.value) { ta.value = text; ta.dispatchEvent(new Event("input")); } });  // a refused command keeps its words
    return true;
  }
  return false;  // unknown: sent as an ordinary message
}
(function slashHints() {
  const ta = $("#msg"); if (!ta) return;
  const pop = h("div", {class: "mentions", id: "slash", role: "listbox", hidden: true}); ta.closest(".composer").prepend(pop);
  ta.addEventListener("input", () => {
    const v = ta.value, m = v.match(/^\/(\w*)$/);
    if (!m) { pop.hidden = true; return; }
    const list = SLASH.filter(([c]) => c.slice(1).startsWith(m[1].toLowerCase()));
    if (!list.length) { pop.hidden = true; return; }
    fill(pop, list.map(([c, label, ex]) => h("button", {class: "item", role: "option", onmousedown: (e) => e.preventDefault(), onclick: () => { ta.value = c + (c === "/task" || c === "/search" ? " " : ""); ta.dispatchEvent(new Event("input")); ta.focus(); }},
      h("span", {class: "t"}, c), h("small", {class: "muted"}, label))));
    pop.hidden = false;
  });
})();

/* ---------- settings: remembered approvals ---------- */
async function approvalsPanel() {
  const list = await api("/api/standing");
  const refresh = async () => fill($("#set-panel"), await approvalsPanel());
  return h("div", {}, h("p", {style: "margin-top:0"}, "When you tap \"Always allow this exact one\" on an approval, that one call runs without asking from then on, for example in a repeating task while nobody is around. It covers only that exact action, by that agent, in that room. Different code, a different link, another agent or another room still asks. Code stops being covered the moment a Python file in the agent's folder changes. Anything that could use secrets, send data out, or run without isolation and a blocked network always asks."),
    list.length ? h("div", {class: "stack"}, list.map((e) => h("div", {class: "perm"}, h("h5", {}, e.agent + " · " + e.tool),
      h("pre", {}, e.summary || ""), e.size > (e.summary || "").length ? h("div", {class: "meta"}, "Shortened here: the full action is " + e.size + " characters long.") : null,
      h("div", {class: "meta"}, "In " + (e.room ? "#" + e.room : "the room where it was approved") + " · allowed by " + e.by + (e.ts ? " · " + whenText(e.ts) : "")),
      e.stale ? h("div", {class: "meta"}, "Paused: a Python file in this agent's folder changed, so it will ask again.") : null,
      h("div", {class: "actions"}, h("button", {class: "btn danger", "aria-label": "Revoke " + e.agent + " " + e.tool, onclick: async () => { await act(() => api("/api/standing/revoke", {agent: e.agent, h: e.h}), "Revoked"); await refresh(); }}, "Revoke")))))
      : h("p", {class: "muted"}, "Nothing is remembered. Approvals always ask."));
}
