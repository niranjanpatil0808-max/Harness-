"use strict";
/* Kintsugi workspace UI. Plain JavaScript, no build step. Markdown via marked, sanitised by DOMPurify (both vendored). */

const $ = (s) => document.querySelector(s);
const S = {token: "", state: null, room: null, agent: null, last: {}, msgs: {}, stick: true, drawer: false, tab: "agent",
           cache: {}, sig: {}, fast: 0, sending: false, file: null};

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else e.setAttribute(k, v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
/* replaceChildren that, like h(), accepts arrays and skips null/false */
function fill(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((c) => c != null && c !== false).map((c) => (c.nodeType ? c : document.createTextNode(String(c)))));
}
const ICONS = {
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>', side: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M9.5 4.5v15"/>',
  panel: '<rect x="3.5" y="4.5" width="17" height="15" rx="3"/><path d="M14.5 4.5v15"/>', send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  theme: '<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>', plus: '<path d="M12 5v14M5 12h14"/>',
};
function icon(name, size = 18) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("width", size); s.setAttribute("height", size);
  s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.8");
  s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name];  // constants above, never user text
  return s;
}
const SPARK = () => { const s = icon("x", 18); s.setAttribute("class", "spark"); s.setAttribute("fill", "currentColor"); s.setAttribute("stroke", "none");
  s.innerHTML = '<path d="M12 2l1.8 7.2L21 12l-7.2 2.8L12 22l-1.8-7.2L3 12l7.2-2.8z"/>'; return s; };

const COLORS = ["#c96442", "#5b7fa6", "#6b8f5e", "#8a6bb0", "#b0834a", "#4f8f8f", "#a65b73"];
function color(name) { let n = 0; for (const c of name) n = (n * 31 + c.charCodeAt(0)) >>> 0; return COLORS[n % COLORS.length]; }
function avatar(name, big) { return h("span", {class: "avatar" + (big ? " lg" : ""), style: "background:" + color(name), "aria-hidden": "true"}, name[0] || "?"); }
const clock = (ts) => new Date(ts * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
const store = {get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
               set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }};

let toastTimer;
function toast(msg, bad) {
  const t = $("#toast"); t.textContent = msg; t.className = "on" + (bad ? " err" : "");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.className = ""), 3500);
}

async function api(path, body) {
  const r = await fetch(path, {method: body ? "POST" : "GET", headers: {"X-Token": S.token, "Content-Type": "application/json"},
                               body: body ? JSON.stringify(body) : undefined});
  let d = {}; try { d = await r.json(); } catch (e) { /* empty */ }
  if (r.status === 401) { connectDialog(); throw new Error("Enter your access token"); }
  if (!r.ok) throw new Error(d.error || "Request failed (" + r.status + ")");
  return d;
}
async function act(fn, ok) { try { const r = await fn(); if (ok) toast(ok); await poll(true); return r; } catch (e) { toast(e.message, true); } }

/* ---------- markdown ---------- */
function md(text) {
  const box = h("div", {class: "body"});
  if (!window.marked || !window.DOMPurify) { box.style.whiteSpace = "pre-wrap"; box.textContent = text; return box; }
  box.innerHTML = DOMPurify.sanitize(marked.parse(text, {gfm: true, breaks: true}));
  box.querySelectorAll("a").forEach((a) => { a.target = "_blank"; a.rel = "noopener noreferrer"; });
  box.querySelectorAll("pre").forEach((pre) => {
    const code = pre.textContent;
    pre.append(h("button", {class: "copy", "aria-label": "Copy code", onclick: async (e) => {
      try { await navigator.clipboard.writeText(code); e.target.textContent = "Copied"; setTimeout(() => (e.target.textContent = "Copy"), 1200); } catch (x) { toast("Copy not available here", true); }
    }}, "Copy"));
  });
  return box;
}

/* ---------- helpers on state ---------- */
const rooms = () => (S.state ? S.state.rooms : []);
const agents = () => (S.state ? S.state.agents : []);
const isAgent = (n) => agents().some((a) => a.name === n);
const curRoom = () => rooms().find((r) => r.name === S.room);
const roomLabel = (r) => (r.kind === "dm" ? r.members.filter((m) => m !== "you")[0] || r.name : r.name);
const roomAgents = (r) => (r ? r.members.filter(isAgent) : []);
const busyIn = (r) => (r && S.state ? S.state.busy.filter((n) => r.members.includes(n)) : []);
const pendingFor = (room) => (S.state ? S.state.approvals.filter((a) => a.room === room) : []);
function focusAgent() {
  const r = curRoom(), ra = roomAgents(r);
  if (S.agent && isAgent(S.agent) && (!r || ra.includes(S.agent) || !ra.length)) return S.agent;
  S.agent = ra[0] || (agents()[0] && agents()[0].name) || null; return S.agent;
}
function sigChanged(key, data) { const s = JSON.stringify(data); if (S.sig[key] === s) return false; S.sig[key] = s; return true; }

/* ---------- sidebar ---------- */
function renderSidebar() {
  const st = S.state; if (!st) return;
  const pend = {}; st.approvals.forEach((a) => (pend[a.room] = (pend[a.room] || 0) + 1));
  if (!sigChanged("side", [st.rooms, st.agents.map((a) => a.name), st.busy, pend, S.room])) return;
  const roomItem = (r) => h("button", {class: "item" + (r.name === S.room ? " on" : ""), onclick: () => openRoom(r.name)},
    r.kind === "dm" ? avatar(roomLabel(r)) : h("span", {class: "muted", style: "width:24px;text-align:center"}, "#"),
    h("span", {class: "t"}, roomLabel(r)), busyIn(r).length ? h("span", {class: "dot", title: "working"}) : null,
    pend[r.name] ? h("span", {class: "badge"}, pend[r.name]) : null);
  const dms = st.rooms.filter((r) => r.kind === "dm"), grp = st.rooms.filter((r) => r.kind !== "dm");
  const side = $("#sidebar"); fill(side,
    h("div", {class: "brand"}, h("img", {src: "/static/logo.svg", alt: ""}), "Kintsugi", h("span", {class: "sp"}),
      h("button", {class: "icon-btn", "aria-label": "Close sidebar", onclick: toggleSidebar}, icon("side"))),
    h("button", {class: "newchat", onclick: newChatDialog}, h("span", {class: "plus"}, "+"), "New chat"),
    h("nav", {class: "nav"},
      dms.length ? [h("h4", {}, "Direct messages"), dms.map(roomItem)] : null,
      grp.length ? [h("h4", {}, "Rooms"), grp.map(roomItem)] : null,
      h("h4", {}, "Agents"),
      st.agents.map((a) => h("button", {class: "item", title: a.persona || a.name, onclick: () => dmWith(a.name)},
        avatar(a.name), h("span", {class: "t"}, a.name), st.busy.includes(a.name) ? h("span", {class: "dot"}) : h("span", {class: "muted", style: "font-size:12px"}, a.tier))),
      h("button", {class: "item muted", onclick: newAgentDialog}, h("span", {style: "width:24px;text-align:center"}, "+"), "New agent")),
    h("div", {class: "side-foot"}, avatar("you"), h("span", {class: "who"}, "you"),
      h("button", {class: "icon-btn", "aria-label": "Change theme", title: "Theme", onclick: cycleTheme}, icon("theme"))));
}
function toggleSidebar() {
  const app = $("#app");
  if (matchMedia("(max-width:860px)").matches) { app.classList.toggle("open"); $("#scrim").hidden = !app.classList.contains("open"); }
  else { app.classList.toggle("collapsed"); store.set("kt-collapsed", app.classList.contains("collapsed") ? "1" : ""); renderTopbar(true); }
}
function closeSidebarMobile() { $("#app").classList.remove("open"); $("#scrim").hidden = true; }
function cycleTheme() {
  const order = ["", "light", "dark"], now = store.get("kt-theme") || "", next = order[(order.indexOf(now) + 1) % 3];
  store.set("kt-theme", next); applyTheme(); toast("Theme: " + (next || "match system"));
}
function applyTheme() { const t = store.get("kt-theme"); if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme; }

/* ---------- top bar ---------- */
function renderTopbar(force) {
  const st = S.state; if (!st) return;
  const r = curRoom(), n = st.approvals.length;
  if (!sigChanged("top", [r, n, S.drawer, $("#app").classList.contains("collapsed")]) && !force) return;
  const collapsed = $("#app").classList.contains("collapsed") || matchMedia("(max-width:860px)").matches;
  fill($("#topbar"),
    collapsed ? h("button", {class: "icon-btn", "aria-label": "Open sidebar", onclick: toggleSidebar}, icon("menu")) : null,
    r ? [r.kind === "dm" ? avatar(roomLabel(r), true) : null,
         h("div", {style: "min-width:0"}, h("div", {class: "title"}, (r.kind === "dm" ? "" : "# ") + roomLabel(r)),
           h("div", {class: "sub"}, r.kind === "dm" ? ((st.agents.find((a) => a.name === roomLabel(r)) || {}).persona || "Direct message") : "Members: " + r.members.join(", ")))] : h("div", {class: "title"}, "Kintsugi"),
    h("span", {class: "sp"}),
    n ? h("button", {class: "pill-btn warn", onclick: () => { const a = st.approvals[0]; if (a.room !== S.room) openRoom(a.room); else $("#scroll").scrollTop = $("#scroll").scrollHeight; }}, n + " waiting for approval") : null,
    h("button", {class: "pill-btn", "aria-pressed": S.drawer, onclick: () => toggleDrawer()}, icon("panel", 16), "Details"));
}

/* ---------- thread ---------- */
function bodyOf(m) {
  if (m.sender === "system") {
    const x = m.text.match(/^@(\S+) Your request to run (\S+) \(approval #(\d+)\)\. ([\s\S]*)$/);
    if (x) {
      const [, who, tool, id, rest] = x, ok = /approved/.test(rest), out = (rest.split("Output:\n")[1] || "").trim();
      return h("div", {class: "sys"}, (ok ? "✓ " : "✕ ") + "Approval #" + id + ": " + who + (ok ? " ran " : " was not allowed to run ") + tool,
        out ? h("details", {style: "margin-top:4px"}, h("summary", {style: "cursor:pointer"}, "Output"), h("pre", {class: "view", style: "text-align:left"}, out)) : null);
    }
    return h("div", {class: "sys"}, m.text);
  }
  if (/^cron-\d+$/.test(m.sender)) return h("div", {class: "sys cron"}, "⏰ Scheduled: " + m.text.replace(/^@\S+\s*/, ""));
  if (m.sender === "you") return h("div", {class: "row me", title: clock(m.ts)}, h("div", {class: "bubble"}, m.text));
  const agent = isAgent(m.sender);
  return h("div", {class: "row"}, avatar(m.sender, true),
    h("div", {class: "body-wrap", style: "flex:1;min-width:0"},
      h("div", {class: "who-line"}, m.sender, h("time", {}, clock(m.ts))),
      agent ? md(m.text) : h("div", {class: "body", style: "white-space:pre-wrap"}, m.text)));
}
function emptyState() {
  const r = curRoom(), ra = roomAgents(r), first = ra[0] || (agents()[0] || {}).name;
  if (!agents().length) return h("div", {class: "hello"}, h("img", {src: "/static/logo.svg", alt: ""}), h("h2", {}, "Create your first agent"),
    h("p", {}, "Agents have their own files, memory and permissions, and they learn from their mistakes."), h("button", {class: "btn primary", onclick: newAgentDialog}, "New agent"));
  const hour = new Date().getHours(), greet = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const tag = r && r.kind === "dm" ? "" : "@" + first + " ";
  const ideas = ["Write a short todo list into todo.txt", "Use python to compute 17 × 23", "Remember that I prefer metric units", "Publish a small hello web app"];
  return h("div", {class: "hello"}, h("img", {src: "/static/logo.svg", alt: ""}), h("h2", {}, greet + "."),
    h("p", {}, r ? (r.kind === "dm" ? "Say something to " + roomLabel(r) + "." : "Mention an agent with @ to get its attention.") : "Pick a chat on the left."),
    r ? h("div", {class: "chips"}, ideas.map((t) => h("button", {class: "chip", onclick: () => { const ta = $("#msg"); ta.value = tag + t; ta.dispatchEvent(new Event("input")); ta.focus(); }}, t))) : null);
}
function renderThread(msgs) {
  const th = $("#thread"), sc = $("#scroll");
  if (S.threadRoom !== S.room) { th.replaceChildren(); S.threadRoom = S.room; }
  const wasNear = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 90 || S.stick;
  if (msgs.length) th.querySelector(".hello")?.remove();
  msgs.forEach((m) => th.append(bodyOf(m)));
  const only = th.children.length === 1 && th.firstChild.classList.contains("hello");
  if (!th.children.length || (only && sigChanged("hello", [S.room, agents().map((a) => a.name)]))) th.replaceChildren(emptyState());
  if (msgs.length) { if (wasNear) { sc.scrollTop = sc.scrollHeight; $("#jump").hidden = true; } else $("#jump").hidden = false; }
  S.stick = false;
}
function sandboxLine(tool) {
  const sb = S.state && S.state.sandbox;
  if (tool !== "run_python" && tool !== "fix_code") return "Read it before you allow it.";
  if (tool === "fix_code") return "Read it before you allow it. This tool runs code outside the isolated sandbox.";
  return sb && sb.isolated ? "Read it before you allow it. It runs isolated: only this agent's folder, " + (sb.network_blocked ? "no network." : "network is not blocked.")
    : "Read it before you allow it. NOT isolated here: it runs with the server's permissions, files and network.";
}
function renderInline() {
  const r = curRoom(), pend = pendingFor(S.room), busy = busyIn(r);
  if (!sigChanged("inline", [S.room, pend, busy])) return;
  const s = $("#scroll"), near = s.scrollHeight - s.scrollTop - s.clientHeight < 90;
  fill($("#inline"),
    pend.map((a) => {
      let args = {}; try { args = JSON.parse(a.args); } catch (e) { /* keep raw */ }
      const code = args.code !== undefined ? args.code : JSON.stringify(args, null, 2);
      return h("div", {class: "perm"}, h("h5", {}, a.agent + " wants to use " + a.tool),
        h("div", {class: "meta"}, sandboxLine(a.tool)),
        h("pre", {}, code.length > 20000 ? code.slice(0, 20000) + "\n…(truncated)" : code),
        h("div", {class: "actions"}, h("button", {class: "btn primary", onclick: (e) => { e.target.disabled = true; act(() => api("/api/approve", {id: a.id, approve: true})); }}, "Allow once"),
          h("button", {class: "btn danger", onclick: (e) => { e.target.disabled = true; act(() => api("/api/approve", {id: a.id, approve: false})); }}, "Deny")));
    }),
    busy.length ? h("div", {class: "working", "aria-live": "polite"}, SPARK(), busy.join(", ") + (busy.length > 1 ? " are" : " is") + " working…") : null);
  if (near) s.scrollTop = s.scrollHeight;
}

/* ---------- composer ---------- */
let mentionIdx = 0, mentionList = [];
function buildComposer() {
  const wrap = $("#composer-wrap");
  const ta = h("textarea", {id: "msg", rows: 1, "aria-label": "Message", autocomplete: "off", enterkeyhint: "send"});
  const send = h("button", {class: "send", id: "send", "aria-label": "Send", disabled: true, onclick: sendMsg}, icon("send"));
  const pop = h("div", {class: "mentions", id: "mentions", role: "listbox", hidden: true});
  fill(wrap, h("div", {class: "composer"}, pop, h("div", {class: "box"}, ta, send)),
    h("div", {class: "hint", id: "hint"}, "Enter to send · Shift+Enter for a new line · @ to mention an agent"));
  ta.addEventListener("input", () => {
    ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight, 220) + "px";
    send.disabled = !ta.value.trim(); store.set("kt-draft-" + S.room, ta.value); showMentions();
  });
  ta.addEventListener("keydown", (e) => {
    if (!pop.hidden && mentionList.length) {
      if (e.key === "ArrowDown") { e.preventDefault(); mentionIdx = (mentionIdx + 1) % mentionList.length; drawMentions(); return; }
      if (e.key === "ArrowUp") { e.preventDefault(); mentionIdx = (mentionIdx - 1 + mentionList.length) % mentionList.length; drawMentions(); return; }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); pickMention(mentionList[mentionIdx]); return; }
      if (e.key === "Escape") { pop.hidden = true; return; }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMsg(); }
  });
  ta.addEventListener("blur", () => setTimeout(() => (pop.hidden = true), 150));
}
function showMentions() {
  const ta = $("#msg"), pop = $("#mentions"), r = curRoom();
  const m = ta.value.slice(0, ta.selectionStart).match(/(^|\s)@([a-z0-9_-]*)$/);
  mentionList = m && r && r.kind !== "dm" ? roomAgents(r).filter((n) => n.startsWith(m[2])) : [];
  mentionIdx = 0; pop.hidden = !mentionList.length; drawMentions();
}
function drawMentions() {
  fill($("#mentions"), mentionList.map((n, i) => h("button", {class: "item" + (i === mentionIdx ? " on" : ""), role: "option", onmousedown: (e) => { e.preventDefault(); pickMention(n); }}, avatar(n), "@" + n)));
}
function pickMention(name) {
  const ta = $("#msg"), pos = ta.selectionStart, before = ta.value.slice(0, pos).replace(/@[a-z0-9_-]*$/, "@" + name + " ");
  ta.value = before + ta.value.slice(pos); ta.selectionStart = ta.selectionEnd = before.length; $("#mentions").hidden = true; ta.dispatchEvent(new Event("input")); ta.focus();
}
async function sendMsg() {
  const ta = $("#msg"), text = ta.value.trim();
  if (!text || !S.room || S.sending) return;
  S.sending = true; S.stick = true; ta.value = ""; ta.dispatchEvent(new Event("input"));
  try { await api("/api/say", {room: S.room, text}); S.fast = 12; await poll(true); }
  catch (e) { toast(e.message, true); ta.value = text; ta.dispatchEvent(new Event("input")); }
  finally { S.sending = false; ta.focus(); }
}
function updateComposer() {
  const r = curRoom(), ta = $("#msg"); if (!ta) return;
  ta.placeholder = !agents().length ? "Create an agent first" : r ? (r.kind === "dm" ? "Message " + roomLabel(r) : "Message #" + r.name + " (use @ to mention an agent)") : "Pick a chat";
  ta.disabled = !r;
}

/* ---------- navigation ---------- */
function openRoom(name) {
  S.room = name; S.last[name] = 0; S.stick = true; S.sig = {}; closeSidebarMobile(); focusAgent();
  const ta = $("#msg"); if (ta) { ta.value = store.get("kt-draft-" + name) || ""; ta.dispatchEvent(new Event("input")); }
  poll(true);
}
async function dmWith(agent) {
  try { const r = await api("/api/dm", {a: "you", b: agent}); S.agent = agent; await poll(true); openRoom(r.room); } catch (e) { toast(e.message, true); }
}

/* ---------- drawer ---------- */
const TABS = [["agent", "Agent"], ["lessons", "Lessons"], ["files", "Files"], ["jobs", "Schedule"], ["apps", "Apps"], ["safety", "Safety"], ["activity", "Log"]];
function toggleDrawer(force) {
  S.drawer = force === undefined ? !S.drawer : force; $("#drawer").hidden = !S.drawer; S.sig.drawer = null; S.sig.top = null;
  renderTopbar(true); if (S.drawer) poll(true);
}
async function loadTab() {
  const a = focusAgent(); if (!a || !S.drawer) return;
  const q = encodeURIComponent(a);
  if (S.tab === "lessons") S.cache.lessons = await api("/api/lessons?agent=" + q);
  if (S.tab === "files") S.cache.files = await api("/api/files?agent=" + q);
  if (S.tab === "activity") S.cache.activity = (await api("/api/audit")).filter((x) => x.agent === a).slice(-40).reverse();
}
function renderDrawer() {
  const d = $("#drawer"); if (!S.drawer) return;
  const a = agents().find((x) => x.name === focusAgent());
  const editing = d.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (editing) return;
  const data = {a, tab: S.tab, c: S.cache[S.tab], jobs: S.state.jobs, file: S.file, room: S.room, names: agents().map((x) => x.name)};
  if (!sigChanged("drawer", data)) return;
  const r = curRoom(), choices = (r && roomAgents(r).length ? roomAgents(r) : agents().map((x) => x.name));
  fill(d,
    h("div", {class: "d-head"}, a ? avatar(a.name, true) : null,
      h("div", {class: "grow"}, choices.length > 1 ? h("select", {"aria-label": "Agent", onchange: (e) => { S.agent = e.target.value; S.file = null; S.sig.drawer = null; poll(true); }},
        choices.map((n) => h("option", {value: n, selected: n === (a && a.name)}, n))) : h("strong", {}, a ? a.name : "No agent")),
      h("button", {class: "icon-btn", "aria-label": "Close details", onclick: () => toggleDrawer(false)}, icon("close"))),
    h("div", {class: "tabs", role: "tablist"}, TABS.map(([k, label]) => h("button", {class: "tab" + (S.tab === k ? " on" : ""), role: "tab", "aria-selected": S.tab === k,
      onclick: () => { S.tab = k; S.sig.drawer = null; S.file = null; poll(true); }}, label))),
    h("div", {class: "d-body"}, a ? tabBody(a) : h("p", {class: "muted"}, "Create an agent to see its details.")));
}
function secretForm(a) {
  const name = h("input", {type: "text", placeholder: "API_TOKEN", "aria-label": "Secret name", autocapitalize: "characters"}), value = h("input", {type: "password", placeholder: "value", "aria-label": "Secret value", autocomplete: "off"});
  return h("div", {class: "stack"}, h("small", {class: "muted"}, "A secret goes into the keychain only. It is never shown again, never sent to the model, and agents can use it only by name when you approve code."), name, value,
    h("button", {class: "btn", onclick: async () => { const ok = await act(() => api("/api/secret", {agent: a.name, name: name.value.trim(), value: value.value}), "Secret saved"); if (ok) { name.value = ""; value.value = ""; } }}, "Save secret"));
}
function tabBody(a) {
  const c = S.cache[S.tab];
  if (S.tab === "agent") {
    const persona = h("textarea", {rows: 4, "aria-label": "Persona", placeholder: "Who is this agent and how should it behave?"}, a.persona);
    const tiers = [["strict", "Ask for everything"], ["auto", "Ask for risky tools"], ["dangerous", "Never ask"]];
    return [h("h4", {}, "Persona"), h("div", {class: "stack"}, persona,
        h("button", {class: "btn", onclick: () => act(() => api("/api/persona", {agent: a.name, persona: persona.value}), "Saved")}, "Save persona")),
      h("h4", {}, "Permissions"), h("div", {class: "seg", role: "group"}, tiers.map(([t]) => h("button", {class: a.tier === t ? "on" : "", "aria-pressed": a.tier === t,
        onclick: () => act(() => api("/api/tier", {agent: a.name, tier: t}), "Permission: " + t)}, t))),
      h("p", {class: "muted", style: "font-size:13px"}, tiers.find((t) => t[0] === a.tier)[1] + ". Tools outside its allow-list are always refused."),
      h("h4", {}, "Secrets"), a.secrets.length ? a.secrets.map((n) => h("div", {class: "card", style: "display:flex;align-items:center;gap:8px"}, h("code", {style: "flex:1"}, n), h("small", {}, "value hidden"),
        h("button", {class: "btn danger", onclick: () => confirmDialog("Remove " + n + "?", "The agent will no longer be able to use it.", "Remove", () => act(() => api("/api/secret/delete", {agent: a.name, name: n}), "Removed"))}, "Remove"))) : h("p", {class: "muted"}, "None."),
      secretForm(a),
      h("h4", {}, "Direct message"), h("button", {class: "btn", onclick: () => dmWith(a.name)}, "Message " + a.name)];
  }
  if (S.tab === "lessons") return [h("p", {class: "muted"}, "When a tool call fails, " + a.name + " writes a short lesson. Lessons are kept if they help later and dropped if they don't."),
    c === undefined ? h("p", {class: "muted"}, "Loading…") : c.length ? c.map((l) => h("div", {class: "card"}, l.text, h("div", {}, h("small", {}, "helped " + l.wins + " of " + l.uses + " uses · " + l.status)))) : h("p", {class: "muted"}, "No lessons yet.")];
  if (S.tab === "files") return [c === undefined ? h("p", {class: "muted"}, "Loading…") : c.length ? c.map((f) => h("button", {class: "item", onclick: () => viewFile(a.name, f)}, h("span", {class: "t"}, f))) : h("p", {class: "muted"}, "No files yet. Ask " + a.name + " to write one."),
    S.file ? [h("h4", {}, S.file.path), h("pre", {class: "view"}, S.file.text)] : null];
  if (S.tab === "jobs") {
    const mine = S.state.jobs.filter((j) => j.agent === a.name), preset = h("select", {"aria-label": "Schedule"},
      [["0 9 * * 1-5", "Every weekday at 09:00"], ["0 9 * * *", "Every day at 09:00"], ["0 * * * *", "Every hour"], ["0 9 * * 1", "Every Monday at 09:00"], ["", "Custom cron…"]].map(([v, l]) => h("option", {value: v}, l)));
    const cron = h("input", {type: "text", placeholder: "min hour day month weekday", "aria-label": "Cron", hidden: true}), what = h("input", {type: "text", placeholder: "What should " + a.name + " do?", "aria-label": "Task"});
    preset.onchange = () => (cron.hidden = preset.value !== "");
    return [h("p", {class: "muted"}, "Times use the server's clock."), mine.length ? mine.map((j) => h("div", {class: "card"}, h("code", {}, j.cron), " in ", j.room, h("div", {}, j.prompt),
        h("button", {class: "btn danger", style: "margin-top:6px", onclick: () => act(() => api("/api/jobs/delete", {id: j.id}), "Removed")}, "Remove"))) : h("p", {class: "muted"}, "Nothing scheduled."),
      h("h4", {}, "New schedule in " + (S.room || "this room")), h("div", {class: "stack"}, preset, cron, what,
        h("button", {class: "btn primary", onclick: () => act(() => api("/api/jobs", {agent: a.name, room: S.room, cron: preset.value || cron.value.trim(), prompt: what.value.trim()}), "Scheduled")}, "Schedule"))];
  }
  if (S.tab === "apps") return a.apps.length ? [h("p", {class: "muted"}, "Apps run in a locked box: no network, no access to your workspace. Links open for one hour."), a.apps.map((n) => h("button", {class: "card item", style: "width:100%", onclick: async () => {
    try { const r = await api("/api/applink?agent=" + encodeURIComponent(a.name) + "&app=" + encodeURIComponent(n)); window.open(r.url, "_blank", "noopener"); } catch (e) { toast(e.message, true); } }}, "▶ " + n))] : h("p", {class: "muted"}, "No apps yet. Ask " + a.name + " to publish one.");
  if (S.tab === "safety") return safetyTab(a);
  if (S.tab === "activity") return c === undefined ? h("p", {class: "muted"}, "Loading…") : c.length ? c.map((x) => h("div", {class: "card"}, h("strong", {}, x.event), h("div", {}, h("small", {}, new Date(x.ts * 1000).toLocaleString() + (x.detail ? " · " + x.detail : ""))))) : h("p", {class: "muted"}, "Nothing yet.");
  return null;
}
function safetyTab(a) {
  const st = S.state, sb = st.sandbox, u = st.usage, r = curRoom();
  return [h("h4", {}, "Where your code runs"), h("div", {class: "card"}, h("strong", {}, sb.isolated ? "Isolated sandbox" : "Not isolated"), h("div", {}, sb.isolated
      ? "Approved code sees only this agent's folder and a read-only system" + (sb.network_blocked ? ", with no network." : ". The network is not blocked here.")
      : "Approved code runs with the server's permissions: it could read files and use the network. Only approve code you would run yourself."), h("small", {}, sb.backend + ": " + sb.note)),
    h("h4", {}, "Where your messages go"), h("div", {class: "card"}, "Whenever an agent thinks, the conversation text (and tool results) is sent to ", h("strong", {}, st.provider), ". Files, secrets and your other chats stay on this server."),
    h("h4", {}, "Cost guard"), h("div", {class: "card"}, u.calls + " model calls today" + (u.limit ? " of " + u.limit + " allowed (resets at midnight UTC)." : ", no limit set.")),
    h("h4", {}, "Your data"), h("div", {class: "stack"},
      h("button", {class: "btn", onclick: exportData}, "Download everything (JSON)"),
      h("button", {class: "btn", onclick: () => confirmDialog("Delete old messages?", "Messages and log entries older than 30 days will be deleted for good.", "Delete", () => act(async () => { const r2 = await api("/api/purge", {days: 30}); toast("Deleted " + r2.deleted + " messages"); }))}, "Delete messages older than 30 days"),
      r && r.kind !== "dm" ? h("button", {class: "btn danger", onclick: () => confirmDialog("Delete room " + r.name + "?", "Its messages, schedules and pending approvals are deleted for good.", "Delete room", async () => { await act(() => api("/api/room/delete", {name: r.name}), "Room deleted"); S.room = null; })}, "Delete this room") : null,
      h("button", {class: "btn danger", onclick: () => confirmDialog("Delete " + a.name + "?", "Its files, apps, lessons, notes, secrets, schedules and chats are deleted for good. This cannot be undone.", "Delete " + a.name, async () => { await act(() => api("/api/agent/delete", {name: a.name}), "Agent deleted"); S.agent = null; S.room = null; })}, "Delete agent " + a.name))];
}
async function exportData() {
  try { const d = await api("/api/export"); const url = URL.createObjectURL(new Blob([JSON.stringify(d, null, 2)], {type: "application/json"}));
    const a = h("a", {href: url, download: "kintsugi-export.json"}); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000); } catch (e) { toast(e.message, true); }
}
function confirmDialog(title, text, label, run) {
  dialog(title, text, h("div", {}), (close) => [h("button", {class: "btn", onclick: close}, "Cancel"), h("button", {class: "btn primary", onclick: () => { close(); run(); }}, label)]);
}
async function viewFile(agent, path) { try { S.file = await api("/api/file?agent=" + encodeURIComponent(agent) + "&path=" + encodeURIComponent(path)); S.sig.drawer = null; renderDrawer(); } catch (e) { toast(e.message, true); } }

/* ---------- dialogs ---------- */
function dialog(title, desc, content, actions, onClose) {
  const root = $("#dialog-root");
  const close = () => { root.replaceChildren(); document.removeEventListener("keydown", esc); if (onClose) onClose(); };
  const esc = (e) => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", esc);
  fill(root, h("div", {class: "overlay", onmousedown: (e) => { if (e.target.classList.contains("overlay")) close(); }},
    h("div", {class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title}, h("h3", {}, title), desc ? h("p", {}, desc) : null, content,
      actions ? h("div", {class: "actions"}, actions(close)) : null)));
  const first = root.querySelector("input,textarea,select"); if (first) first.focus();
  return close;
}
function connectDialog() {
  if ($("#dialog-root .dialog")) return;
  const input = h("input", {type: "password", placeholder: "Access token", autocomplete: "off", "aria-label": "Access token"});
  const go = (close) => { S.token = input.value.trim(); store.set("kt-token", S.token); try { sessionStorage.setItem("kt", S.token); } catch (e) { /* ok */ } close(); poll(true); };
  dialog("Connect to your workspace", "Paste the access token printed by `kintsugi workspace serve` (or the KINTSUGI_TOKEN you set). It stays in this browser.",
    h("form", {onsubmit: (e) => e.preventDefault()}, input),
    (close) => [h("button", {class: "btn primary", onclick: () => go(close)}, "Connect")]);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") $("#dialog-root .btn.primary").click(); });
}
function newChatDialog() {
  const list = agents().map((a) => h("button", {class: "item", onclick: () => { close(); dmWith(a.name); }}, avatar(a.name), h("span", {class: "t"}, a.name), h("small", {class: "muted"}, a.persona.slice(0, 40))));
  const close = dialog("New chat", "Message one agent directly, or start a group room.", h("div", {},
    list.length ? list : h("p", {class: "muted"}, "No agents yet."),
    h("div", {style: "display:flex;gap:8px;margin-top:10px"}, h("button", {class: "btn", onclick: () => { close(); newRoomDialog(); }}, "New group room"), h("button", {class: "btn", onclick: () => { close(); newAgentDialog(); }}, "New agent"))),
    (c) => [h("button", {class: "btn", onclick: c}, "Close")]);
}
function newAgentDialog() {
  const name = h("input", {type: "text", placeholder: "alice", "aria-label": "Name", autocapitalize: "none"}), persona = h("textarea", {rows: 3, placeholder: "You are a careful research assistant."});
  const tier = h("select", {}, h("option", {value: "auto"}, "auto: ask before risky tools"), h("option", {value: "strict"}, "strict: ask before everything"), h("option", {value: "dangerous"}, "dangerous: never ask"));
  dialog("New agent", "Lowercase letters, digits, - and _. It gets its own folder, memory and permissions.", h("div", {},
    h("label", {}, "Name"), name, h("label", {}, "Persona (optional)"), persona, h("label", {}, "Permissions"), tier),
    (close) => [h("button", {class: "btn", onclick: close}, "Cancel"), h("button", {class: "btn primary", onclick: async () => {
      const ok = await act(() => api("/api/agents", {name: name.value.trim(), persona: persona.value, tier: tier.value}), "Agent created");
      if (ok) { close(); dmWith(name.value.trim()); } }}, "Create")]);
}
function newRoomDialog() {
  const name = h("input", {type: "text", placeholder: "project-x", "aria-label": "Room name", autocapitalize: "none"});
  const boxes = agents().map((a) => h("label", {style: "display:flex;gap:8px;align-items:center;font-weight:400"}, h("input", {type: "checkbox", value: a.name, style: "width:auto"}), a.name));
  dialog("New group room", "Agents answer when you @mention them. Agents can also mention each other, up to 4 replies in a row.", h("div", {}, h("label", {}, "Name"), name, h("label", {}, "Agents"), boxes),
    (close) => [h("button", {class: "btn", onclick: close}, "Cancel"), h("button", {class: "btn primary", onclick: async () => {
      const members = ["you", ...[...document.querySelectorAll("#dialog-root input[type=checkbox]:checked")].map((b) => b.value)];
      const ok = await act(() => api("/api/rooms", {name: name.value.trim(), members}), "Room created");
      if (ok) { close(); openRoom(name.value.trim()); } }}, "Create")]);
}

/* ---------- polling ---------- */
let polling = false, again = false, timer = null;
async function poll(now) {
  if (!S.token) { connectDialog(); return; }
  if (polling) { again = true; return; }
  polling = true; clearTimeout(timer);
  try {
    S.state = await api("/api/state");
    if (!S.room || !curRoom()) { const first = rooms().find((r) => r.kind !== "dm") || rooms()[0]; if (first) { S.room = first.name; S.last[S.room] = 0; S.stick = true; const ta = $("#msg"); if (ta) ta.value = store.get("kt-draft-" + S.room) || ""; } }
    focusAgent(); renderSidebar(); renderTopbar(); updateComposer();
    if (S.room) {
      const after = S.last[S.room] || 0, fresh = await api("/api/messages?room=" + encodeURIComponent(S.room) + "&after=" + after);
      const msgs = fresh.filter((m) => m.id > after);
      if (msgs.length) S.last[S.room] = msgs[msgs.length - 1].id;
      renderThread(msgs);
    } else renderThread([]);
    renderInline();
    if (S.drawer) { await loadTab(); renderDrawer(); }
    $("#main").classList.remove("offline");
  } catch (e) { if (!/access token/.test(e.message)) toast(e.message === "Failed to fetch" ? "Can't reach the workspace. Retrying…" : e.message, true); }
  finally {
    polling = false;
    if (again) { again = false; poll(); return; }
    const busy = (S.state && S.state.busy.length > 0) || S.fast > 0;
    if (S.fast > 0) S.fast--;
    timer = setTimeout(poll, document.hidden ? 8000 : busy ? 800 : 2500);
  }
}

/* ---------- start ---------- */
function init() {
  applyTheme();
  const m = location.hash.match(/token=([^&]+)/);
  if (m) { S.token = decodeURIComponent(m[1]); store.set("kt-token", S.token); history.replaceState(null, "", location.pathname); }
  else S.token = store.get("kt-token") || "";
  if (store.get("kt-collapsed")) $("#app").classList.add("collapsed");
  $("#scrim").addEventListener("click", closeSidebarMobile);
  $("#scroll").addEventListener("scroll", () => { const s = $("#scroll"); if (s.scrollHeight - s.scrollTop - s.clientHeight < 90) $("#jump").hidden = true; }, {passive: true});
  $("#jump").addEventListener("click", () => { const s = $("#scroll"); s.scrollTop = s.scrollHeight; $("#jump").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#dialog-root .dialog")) { if (S.drawer) toggleDrawer(false); closeSidebarMobile(); } });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(true); });
  buildComposer(); $("#sidebar").replaceChildren(h("div", {class: "brand"}, h("img", {src: "/static/logo.svg", alt: ""}), "Kintsugi"));
  poll(true);
}
init();
