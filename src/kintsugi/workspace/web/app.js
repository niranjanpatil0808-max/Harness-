"use strict";
/* Kintsugi workspace UI. Plain JavaScript, no build step. Markdown via marked, sanitised by DOMPurify (both vendored). */

const $ = (s) => document.querySelector(s);
const IS_STANDALONE = () => matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
const IS_IOS = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const S = {loadedRooms: {}, installEvent: null, token: "", state: null, room: null, agent: null, last: {}, msgs: {}, stick: true, drawer: false, tab: "agent",
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
  close: '<path d="M6 6l12 12M18 6 6 18"/>', clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>', mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>', speaker: '<path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 9a4 4 0 0 1 0 6"/>', gear: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>', plus: '<path d="M12 5v14M5 12h14"/>',
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
  const r = await fetch(path, {method: body ? "POST" : "GET", headers: {"X-Token": S.token, "Content-Type": "application/json", "X-Visible": document.visibilityState === "visible" ? "1" : "0"},
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
  if (!sigChanged("side", [st.rooms, st.agents.map((a) => a.name), st.busy, pend, S.room, st.improve, !!S.installEvent, IS_STANDALONE(), st.jobs.map((j) => [j.id, j.enabled]), seen(), st.rooms.map((r) => r.last_other)])) return;
  const roomItem = (r) => h("button", {class: "item" + (r.name === S.room ? " on" : ""), onclick: () => openRoom(r.name)},
    r.kind === "dm" ? avatar(roomLabel(r)) : h("span", {class: "muted", style: "width:24px;text-align:center"}, "#"),
    h("span", {class: "t", style: isUnread(r) && r.name !== S.room ? "font-weight:700" : ""}, roomLabel(r)), busyIn(r).length ? h("span", {class: "dot", title: "working"}) : (isUnread(r) && r.name !== S.room ? h("span", {class: "dot", title: "new", style: "animation:none"}) : null),
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
      h("button", {class: "item muted", onclick: newAgentDialog}, h("span", {style: "width:24px;text-align:center"}, "+"), "New agent"),
      h("button", {class: "item muted", onclick: () => automationsDialog()}, h("span", {style: "width:24px;text-align:center"}, "⏰"), "Automations", jobBadge()),
      canInstall() ? h("button", {class: "item muted", onclick: installApp}, h("span", {style: "width:24px;text-align:center"}, "⤓"), "Install the app") : null),
    h("div", {class: "side-foot"}, avatar("you"), h("span", {class: "who"}, "you"),
      h("button", {class: "icon-btn", "aria-label": "Change theme", title: "Theme", onclick: cycleTheme}, icon("theme")),
      h("button", {class: "icon-btn", "aria-label": "Settings", title: "Settings: self-improvement", onclick: settingsDialog}, icon("gear"))));
}
/* what you have already seen in each room, kept on this device */
const seen = () => { try { return JSON.parse(store.get("kt-seen") || "{}"); } catch (e) { return {}; } };
const isUnread = (r) => (r.last_other || 0) > (seen()[r.name] || 0);
function markSeen(room) {
  const r = rooms().find((x) => x.name === room); if (!r || !r.last_other) return;
  const s = seen(); if ((s[room] || 0) >= r.last_other) return;
  s[room] = r.last_other; store.set("kt-seen", JSON.stringify(s)); S.sig.side = null;
}
function syncUnread() {
  if (!S.state) return;
  if (document.visibilityState === "visible" && S.room) markSeen(S.room);
  const n = rooms().filter(isUnread).length;
  document.title = (n ? "(" + n + ") " : "") + "Kintsugi";
  try { if (navigator.setAppBadge) { if (n) navigator.setAppBadge(n); else navigator.clearAppBadge && navigator.clearAppBadge(); } } catch (e) { /* not supported */ }
}
const jobBadge = () => { const n = S.state ? S.state.jobs.filter((j) => j.enabled).length : 0; return n ? h("span", {class: "muted", style: "margin-left:auto;font-size:12px"}, n + " on") : null; };
const canInstall = () => !IS_STANDALONE() && (!!S.installEvent || IS_IOS);
async function installApp() {
  if (S.installEvent) {
    S.installEvent.prompt();
    try { await S.installEvent.userChoice; } catch (e) { /* dismissed */ }
    S.installEvent = null; S.sig.side = null; renderSidebar(); return;
  }
  dialog("Install on your iPhone or iPad", "Safari has no install button, but it takes two taps:", h("ol", {style: "line-height:1.8"},
    h("li", {}, "Tap the Share button (the square with an arrow) in Safari."), h("li", {}, "Choose “Add to Home Screen”, then tap Add.")),
    (close) => [h("button", {class: "btn primary", onclick: close}, "Got it")]);
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
  const imp = st.improve || {};
  if (!sigChanged("top", [r, n, S.drawer, $("#app").classList.contains("collapsed"), imp.running, imp.pending]) && !force) return;
  const collapsed = $("#app").classList.contains("collapsed") || matchMedia("(max-width:860px)").matches;
  fill($("#topbar"),
    collapsed ? h("button", {class: "icon-btn", "aria-label": "Open sidebar", onclick: toggleSidebar}, icon("menu")) : null,
    r ? [r.kind === "dm" ? avatar(roomLabel(r), true) : null,
         h("div", {style: "min-width:0"}, h("div", {class: "title"}, (r.kind === "dm" ? "" : "# ") + roomLabel(r)),
           h("div", {class: "sub"}, r.kind === "dm" ? ((st.agents.find((a) => a.name === roomLabel(r)) || {}).persona || "Direct message") : "Members: " + r.members.join(", ")))] : h("div", {class: "title"}, "Kintsugi"),
    h("span", {class: "sp"}),
    n ? h("button", {class: "pill-btn warn", onclick: () => { const a = st.approvals[0]; if (a.room !== S.room) openRoom(a.room); else $("#scroll").scrollTop = $("#scroll").scrollHeight; }}, n + " waiting for approval") : null,
    imp.running ? h("button", {class: "pill-btn", onclick: settingsDialog, title: imp.progress || ""}, SPARK(), "Studying…") : null,
    imp.pending ? h("button", {class: "pill-btn", onclick: settingsDialog}, imp.pending + " improvement" + (imp.pending > 1 ? "s" : "") + " to review") : null,
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
  if (/^cron-\d+$/.test(m.sender)) {
    const job = S.state && S.state.jobs.find((j) => "cron-" + j.id === m.sender), body = m.text.replace(/^@\S+\s*/, "");
    return h("div", {class: "sys cron"}, "⏰ " + (job && job.title ? job.title : "Scheduled: " + body.slice(0, 90)));
  }
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
  msgs.forEach((m) => { th.append(bodyOf(m)); if (m.sender === "you") (S.talked = S.talked || {})[S.room] = true; });
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
  const spk = CAN_SPEAK ? h("button", {class: "icon-btn", id: "spk", "aria-label": "Read replies aloud", "aria-pressed": "false", title: "Read replies aloud", onclick: toggleSpeakSetting}, icon("speaker")) : null;
  const mic = SR ? h("button", {class: "icon-btn", id: "mic", "aria-label": "Speak your message", title: "Speak your message", onclick: toggleListening}, icon("mic")) : null;
  fill(wrap, h("div", {class: "composer"}, pop, h("div", {id: "starters", class: "strip"}), h("div", {id: "to", class: "strip"}), h("div", {class: "box"}, ta, spk, mic, send)),
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
  const ta = $("#msg"); let text = ta.value.trim();
  if (!text || !S.room || S.sending) return;
  const target = recipient(); if (target && !/(^|\s)@[a-z]/.test(text)) text = "@" + target + " " + text;  // no need to type @ in a room
  stopSpeaking(); S.sending = true; S.stick = true; ta.value = ""; ta.dispatchEvent(new Event("input"));
  (S.talked = S.talked || {})[S.room] = true; updateComposer();
  try { await api("/api/say", {room: S.room, text}); S.fast = 12; await poll(true); }
  catch (e) { toast(e.message, true); ta.value = text; ta.dispatchEvent(new Event("input")); }
  finally { S.sending = false; ta.focus(); }
}
/* who a plain message in a room goes to: the agent you picked, else the one you last spoke to, else the first */
function recipient() {
  const r = curRoom(); if (!r || r.kind === "dm") return null;
  const ra = roomAgents(r), pick = (S.to || {})[r.name];
  return ra.includes(pick) ? pick : ra[0] || null;
}
function starterIdeas() {
  const ideas = [["Write a short todo list into a file", "write a short todo list into todo.txt"], ["Work something out with Python", "use python to compute 17 × 23 and show me the result"],
    ["Remember a preference", "remember that I prefer metric units"], ["What can you do?", "what can you do for me? Keep it short."]];
  if (S.state && S.state.search_configured) ideas.splice(1, 0, ["Search the web", "search the web for the latest news about AI and summarise it with sources"]);
  return ideas;
}
function updateComposer() {
  const r = curRoom(), ta = $("#msg"); if (!ta) return;
  ta.placeholder = !agents().length ? "Create an agent first" : r ? (r.kind === "dm" ? "Message " + roomLabel(r) : "Message " + (recipient() ? "@" + recipient() : "#" + r.name)) : "Pick a chat";
  ta.disabled = !r;
  const to = $("#to"), st = $("#starters"); if (!to) return;
  const ra = r && r.kind !== "dm" ? roomAgents(r) : [];
  if (sigChanged("to", [r && r.name, ra, recipient()])) fill(to, ra.length > 1 ? [h("span", {class: "muted", style: "font-size:13px"}, "To"), ...ra.map((n) => h("button", {class: "chip" + (n === recipient() ? " on" : ""), "aria-pressed": n === recipient(), onclick: () => { (S.to = S.to || {})[r.name] = n; S.sig.to = null; updateComposer(); $("#msg").focus(); }}, "@" + n))] : []);
  const show = !!r && agents().length > 0 && !(S.talked || {})[r.name];
  if (sigChanged("starters", [show, r && r.name, S.state && S.state.search_configured])) fill(st, show ? starterIdeas().map(([label, text]) => h("button", {class: "chip", onclick: () => { ta.value = text; ta.dispatchEvent(new Event("input")); ta.focus(); }}, label)) : []);
}

/* ---------- voice (the browser's own speech: free; audio may be processed by Google or Apple) ---------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const CAN_SPEAK = "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
const LANGS = [["", "Automatic (my phone's language)"], ["en-US", "English (US)"], ["en-GB", "English (UK)"], ["en-IN", "English (India)"], ["hi-IN", "Hindi"], ["mr-IN", "Marathi"],
  ["es-ES", "Spanish"], ["fr-FR", "French"], ["de-DE", "German"], ["pt-BR", "Portuguese (Brazil)"], ["ar-SA", "Arabic"], ["ja-JP", "Japanese"], ["zh-CN", "Chinese"]];
const voice = () => { try { return {speak: false, handsfree: false, lang: "", ...JSON.parse(store.get("kt-voice") || "{}")}; } catch (e) { return {speak: false, handsfree: false, lang: ""}; } };
function saveVoice(v) { store.set("kt-voice", JSON.stringify(v)); syncVoiceButtons(); }
const voiceLang = () => voice().lang || navigator.language || "en-US";
let recog = null, listening = false;
function syncVoiceButtons() {
  const spk = $("#spk"), mic = $("#mic");
  if (spk) { spk.setAttribute("aria-pressed", String(!!voice().speak)); spk.style.color = voice().speak ? "var(--accent)" : ""; }
  if (mic) { mic.classList.toggle("rec", listening); mic.setAttribute("aria-label", listening ? "Stop listening" : "Speak your message"); }
}
function toggleSpeakSetting() { const v = voice(); v.speak = !v.speak; saveVoice(v); if (!v.speak) stopSpeaking(); toast(v.speak ? "Replies will be read aloud" : "Read-aloud off"); }
function toggleListening() { if (listening) { if (recog) recog.stop(); return; } stopSpeaking(); startListening(); }
function startListening() {
  if (!SR) { toast("This browser can't do voice input. Chrome and Safari can.", true); return; }
  const ta = $("#msg"); if (!ta || ta.disabled) return;
  const base = ta.value.trim() ? ta.value.trim() + " " : "";
  let heard = "";
  recog = new SR(); recog.lang = voiceLang(); recog.interimResults = true; recog.continuous = false; recog.maxAlternatives = 1;
  recog.onstart = () => { listening = true; syncVoiceButtons(); };
  recog.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) { const r = e.results[i]; if (r.isFinal) heard += r[0].transcript; else interim += r[0].transcript; }
    ta.value = base + heard + interim; ta.dispatchEvent(new Event("input"));
  };
  recog.onerror = (e) => {
    const why = {"not-allowed": "Microphone blocked. Allow it for this site in your browser settings.", "service-not-allowed": "Voice input is turned off for this browser.",
      "no-speech": "I didn't hear anything.", "audio-capture": "No microphone found.", "network": "Voice input needs an internet connection."};
    if (e.error !== "aborted") toast(why[e.error] || "Voice error: " + e.error, true);
  };
  recog.onend = () => { listening = false; syncVoiceButtons(); if (voice().handsfree && heard.trim()) sendMsg(); };
  try { recog.start(); } catch (e) { /* already running */ }
}
function speakable(text) {
  return text.replace(/```[\s\S]*?```/g, " (code omitted) ").replace(/`([^`]*)`/g, "$1").replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/https?:\/\/\S+/g, " link ").replace(/[*_#>~|]/g, "").replace(/\s+/g, " ").trim().slice(0, 700);
}
function speak(text) {
  if (!CAN_SPEAK) return;
  const t = speakable(text); if (!t) return;
  const u = new SpeechSynthesisUtterance(t); u.lang = voiceLang();
  u.onend = () => { if (voice().handsfree && SR && !speechSynthesis.speaking && !S.sending) setTimeout(startListening, 300); };
  speechSynthesis.speak(u);
}
function stopSpeaking() { if (CAN_SPEAK) speechSynthesis.cancel(); }
function maybeSpeak(msgs) { if (voice().speak) for (const m of msgs) if (isAgent(m.sender)) speak(m.text); }

/* ---------- automations ---------- */
const DAYS = [["daily", "Every day"], ["weekdays", "Weekdays"], ["weekends", "Weekends"], ["mon", "Mondays"], ["tue", "Tuesdays"], ["wed", "Wednesdays"], ["thu", "Thursdays"], ["fri", "Fridays"], ["sat", "Saturdays"], ["sun", "Sundays"]];
const KIND_INFO = {briefing: ["☀️", "Daily briefing", "News on your topics, summarised with sources."], monitor: ["👀", "Watch something", "Tell me only when something important changes."],
  report: ["📄", "Research report", "A short sourced report, now or on a schedule."], custom: ["✍️", "Your own task", "Any instruction, on a schedule."]};
const whenText = (ts) => { if (!ts) return ""; const d = new Date(ts * 1000), now = new Date(), t = d.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  return (days === 0 ? "Today " : days === 1 ? "Tomorrow " : d.toLocaleDateString([], {weekday: "short"}) + " ") + t; };
async function useMyTimezone() {
  const name = Intl.DateTimeFormat().resolvedOptions().timeZone || "", offset = -new Date().getTimezoneOffset();
  return act(() => api("/api/timezone", {name, offset_minutes: offset}), "Time zone set to " + (name || "your phone's offset"));
}
async function automationsDialog() {
  let d;
  try { d = await api("/api/automations"); } catch (e) { toast(e.message, true); return; }
  const list = h("div", {id: "auto-list"}), top = h("div", {id: "auto-top"});
  const draw = async () => {
    try { d = await api("/api/automations"); } catch (e) { return; }
    fill(top, h("div", {class: "card"}, d.timezone.set ? ["Times are in your time zone: ", h("strong", {}, d.timezone.name || "UTC" + (d.timezone.offset_minutes >= 0 ? "+" : "") + d.timezone.offset_minutes / 60), " (now " + d.server_time.slice(11) + ")."]
        : ["Times use the server's clock until you set your time zone. ", h("button", {class: "btn", style: "margin-top:6px", onclick: async () => { await useMyTimezone(); draw(); }}, "Use my phone's time zone")]),
      !d.search ? h("div", {class: "card"}, "Web search is off, so briefings and watchers can only use the agent's notes. ", h("button", {class: "btn", style: "margin-top:6px", onclick: () => settingsDialog("search")}, "Set up search")) : null);
    fill(list, d.jobs.length ? d.jobs.map((j) => h("div", {class: "card"}, h("div", {style: "display:flex;gap:8px;align-items:baseline"}, h("strong", {style: "flex:1"}, (KIND_INFO[j.kind] ? KIND_INFO[j.kind][0] + " " : "") + (j.title || "Automation")),
        h("small", {class: "muted"}, j.enabled ? "On" : "Paused")), h("div", {class: "muted", style: "font-size:13px"}, j.schedule + " · " + j.agent + " in " + (j.room.startsWith("dm-") ? "your chat" : "#" + j.room)),
      h("div", {class: "muted", style: "font-size:13px"}, j.enabled ? "Next: " + (whenText(j.next_run_ts) || "soon") : "Paused", j.last_run_ts ? " · Last: " + whenText(j.last_run_ts) : "", j.runs ? " · ran " + j.runs + "×" : ""),
      h("div", {style: "display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"}, h("button", {class: "btn", onclick: async () => { await act(() => api("/api/automations/toggle", {id: j.id, enabled: !j.enabled}), j.enabled ? "Paused" : "Resumed"); draw(); }}, j.enabled ? "Pause" : "Resume"),
        h("button", {class: "btn", onclick: async () => { await act(() => api("/api/automations/run", {id: j.id}), "Running now. The answer will appear in the chat."); }}, "Run now"),
        h("button", {class: "btn danger", onclick: () => confirmDialog("Delete this automation?", j.title || "", "Delete", async () => { await act(() => api("/api/jobs/delete", {id: j.id}), "Deleted"); draw(); })}, "Delete")))) : h("p", {class: "muted"}, "No automations yet. Pick one below."));
  };
  const choices = h("div", {style: "display:grid;gap:8px"}, Object.entries(KIND_INFO).map(([k, [emoji, name, blurb]]) => h("button", {class: "card item", style: "width:100%;text-align:left;display:block;margin:0", onclick: () => newAutomationDialog(k, draw)},
    h("strong", {}, emoji + " " + name), h("div", {class: "muted", style: "font-size:13px"}, blurb))));
  const close = dialog("Automations", "Agents that work on a schedule and message you the result.", h("div", {}, top, list, h("h4", {style: "margin:16px 0 6px;font-size:13px;color:var(--muted)"}, "New automation"), choices),
    (c) => [h("button", {class: "btn primary", onclick: c}, "Done")]);
  close.dialog.style.width = "min(560px,100%)";
  await draw();
}
function newAutomationDialog(kind, onDone) {
  const [emoji, name] = KIND_INFO[kind];
  const agentsList = agents();
  if (!agentsList.length) { toast("Create an agent first", true); return; }
  const agent = h("select", {"aria-label": "Agent"}, agentsList.map((a) => h("option", {value: a.name}, a.name)));
  const time = h("input", {type: "time", value: "08:00", "aria-label": "Time"});
  const days = h("select", {"aria-label": "Days"}, DAYS.map(([v, l]) => h("option", {value: v}, l)));
  const topics = h("textarea", {rows: 3, placeholder: "One per line, e.g.\nAI news\nStartup funding", "aria-label": "Topics"});
  const query = h("input", {type: "text", placeholder: "e.g. new electric scooter recalls", "aria-label": "What to watch"});
  const topic = h("input", {type: "text", placeholder: "e.g. The electric scooter market in India", "aria-label": "Research topic"});
  const prompt = h("textarea", {rows: 3, placeholder: "What should the agent do?", "aria-label": "Task"});
  const when = h("label", {style: "display:flex;gap:8px;align-items:center;font-weight:400"}, h("input", {type: "checkbox", id: "auto-now", style: "width:auto"}), "Just run it once, now");
  const row = (label, el) => h("div", {style: "margin:12px 0"}, h("label", {style: "margin:0 0 4px"}, label), el);
  const fields = {briefing: [row("Topics", topics)], monitor: [row("What should I watch for?", query)], report: [row("What should I research?", topic)], custom: [row("Task", prompt)]}[kind];
  const schedule = h("div", {id: "auto-when"}, row("Time", time), row("Days", days));
  const content = h("div", {}, row("Which agent?", agent), ...fields, kind === "report" ? when : null, schedule);
  if (kind === "report") when.querySelector("input").onchange = (e) => (schedule.hidden = e.target.checked);
  dialog(emoji + " " + name, KIND_INFO[kind][2], content, (close) => [h("button", {class: "btn", onclick: close}, "Cancel"), h("button", {class: "btn primary", onclick: async () => {
    try {
      const a = state_agent_room(agent.value);
      const body = {kind, agent: agent.value, room: await a, topics: topics.value.split("\n"), query: query.value, topic: topic.value, prompt: prompt.value};
      const once = kind === "report" && when.querySelector("input").checked;
      if (!once) { body.time = time.value; body.days = days.value; }
      const r = await api("/api/automations", body);
      close(); toast((once ? "Started. The report will appear in the chat." : "Automation created.") + (r.warning ? " " + r.warning : "")); await poll(true); if (onDone) onDone();
    } catch (e) { toast(e.message, true); } }}, kind === "report" ? "Start" : "Create")]);
}
async function state_agent_room(agent) {
  const r = rooms().find((x) => x.kind === "dm" && x.members.includes(agent) && x.members.includes("you")) || rooms().find((x) => x.members.includes(agent));
  if (r) return r.name;
  return (await api("/api/dm", {a: "you", b: agent})).room;
}

/* ---------- notifications (Web Push; the notification itself carries no text) ---------- */
const b64uToBytes = (text) => { const pad = "=".repeat((4 - text.length % 4) % 4), raw = atob((text + pad).replace(/-/g, "+").replace(/_/g, "/")); return Uint8Array.from(raw, (c) => c.charCodeAt(0)); };
async function pushState() {
  const supported = "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
  if (!supported) return {kind: "unsupported"};
  if (IS_IOS && !IS_STANDALONE()) return {kind: "ios-install"};
  const info = await api("/api/push");
  if (!info.available) return {kind: "server-off"};
  let sub = null;
  try { const reg = await Promise.race([navigator.serviceWorker.ready, new Promise((_, no) => setTimeout(() => no(new Error("slow")), 4000))]); sub = await reg.pushManager.getSubscription(); } catch (e) { return {kind: "unsupported"}; }
  return {kind: sub ? "on" : "off", info, sub, permission: Notification.permission};
}
async function enableNotifications(info) {
  const perm = await Notification.requestPermission();
  if (perm !== "granted") { toast("Notifications are blocked. Allow them for this site in your browser or phone settings.", true); return; }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: b64uToBytes(info.public_key)});
  await api("/api/push/subscribe", sub.toJSON());
  toast("Notifications are on");
}
async function disableNotifications(sub) { try { await api("/api/push/unsubscribe", {endpoint: sub.endpoint}); await sub.unsubscribe(); toast("Notifications are off"); } catch (e) { toast(e.message, true); } }
async function pushRow() {
  const draw = async () => fill($("#push-row"), await pushRow());
  let st; try { st = await pushState(); } catch (e) { return h("p", {class: "muted"}, e.message); }
  const say = (t) => h("p", {class: "muted", style: "margin:4px 0"}, t);
  const privacy = h("small", {class: "muted", style: "display:block;margin-top:6px"}, "A notification only says “You have something new”. It never contains the message, and it is sent only when an agent wrote or something needs your approval and you are not using the app.");
  if (st.kind === "unsupported") return h("div", {}, say("This browser cannot show notifications. Chrome on Android, and Safari on iPhone with the app added to the Home Screen, can."));
  if (st.kind === "ios-install") return h("div", {}, say("On iPhone, first add the app to your Home Screen (Share, then Add to Home Screen), open it from there, and come back here."));
  if (st.kind === "server-off") return h("div", {}, say("This server cannot send notifications yet (it needs the optional “cryptography” package)."));
  if (st.kind === "on") return h("div", {}, say("Notifications are on for this device."), h("div", {style: "display:flex;gap:8px;flex-wrap:wrap;margin-top:6px"},
    h("button", {class: "btn", onclick: async () => { try { const r = await api("/api/push/test", {}); toast(r.delivered ? "Sent. It should arrive in a moment." : "The push service did not accept it", !r.delivered); } catch (e) { toast(e.message, true); } }}, "Send a test"),
    h("button", {class: "btn danger", onclick: async () => { await disableNotifications(st.sub); draw(); }}, "Turn off")), privacy);
  return h("div", {}, say(st.permission === "denied" ? "Notifications are blocked for this site. Allow them in your browser or phone settings, then try again." : "Get a nudge on your phone when an agent finishes something or needs you."),
    h("button", {class: "btn primary", style: "margin-top:6px", onclick: async () => { try { await enableNotifications(st.info); } catch (e) { toast("Could not turn on notifications: " + e.message, true); } draw(); }}, "Turn on notifications"), privacy);
}
const tzRow = (t) => h("div", {}, h("p", {class: "muted", style: "margin:4px 0"}, t.set ? "Automations run in " + (t.name || "your phone's offset") + " (now " + t.now.slice(11) + ")." : "Not set: the server's clock is used (now " + t.now.slice(11) + ")."),
  h("button", {class: "btn", onclick: async () => { await useMyTimezone(); const r = await api("/api/timezone"); fill($("#tz-row"), tzRow(r)); }}, "Use my phone's time zone"));
async function generalPanel() {
  const v = voice();
  let tone = {style: "fun", custom: "", labels: {}, examples: {}};
  try { tone = await api("/api/tone"); } catch (e) { /* shown by the poll */ }
  const custom = h("textarea", {rows: 2, maxlength: 300, placeholder: "e.g. Talk like a calm coach. Short sentences.", "aria-label": "Custom style"}, tone.custom || "");
  custom.hidden = tone.style !== "custom";
  const hint = h("small", {class: "muted", style: "display:block;margin-top:4px"}, tone.examples[tone.style] || "");
  const style = h("select", {"aria-label": "Reply style", onchange: () => { custom.hidden = style.value !== "custom"; hint.textContent = style.value === "custom" ? "Your own words. It can change how replies sound, never the safety rules." : (tone.examples[style.value] || ""); }},
    Object.entries(tone.labels).map(([k, l]) => h("option", {value: k, selected: tone.style === k}, l)));
  const pushRowInitial = await pushRow();
  let tzInfo = {name: "", offset_minutes: 0, set: false, now: ""};
  try { tzInfo = await api("/api/timezone"); } catch (e) { /* shown by the poll */ }
  const saveStyle = () => act(() => api("/api/tone", {style: style.value, custom: custom.value}), "Style saved");
  const speakBox = h("input", {type: "checkbox", checked: v.speak, disabled: !CAN_SPEAK, style: "width:auto", onchange: (e) => { saveVoice({...voice(), speak: e.target.checked}); if (!e.target.checked) stopSpeaking(); }});
  const handsBox = h("input", {type: "checkbox", checked: v.handsfree, disabled: !SR || !CAN_SPEAK, style: "width:auto", onchange: (e) => { const nv = {...voice(), handsfree: e.target.checked}; if (e.target.checked) nv.speak = true; saveVoice(nv); speakBox.checked = nv.speak; }});
  const lang = h("select", {"aria-label": "Voice language", onchange: (e) => saveVoice({...voice(), lang: e.target.value})}, LANGS.map(([c, l]) => h("option", {value: c, selected: v.lang === c}, l)));
  const theme = h("select", {"aria-label": "Theme", onchange: (e) => { store.set("kt-theme", e.target.value); applyTheme(); }}, [["", "Match my phone"], ["light", "Light"], ["dark", "Dark"]].map(([c, l]) => h("option", {value: c, selected: (store.get("kt-theme") || "") === c}, l)));
  const row = (label, el, note) => h("div", {style: "margin:12px 0"}, h("label", {style: "margin:0 0 4px"}, label), el, note ? h("small", {class: "muted", style: "display:block;margin-top:2px"}, note) : null);
  return h("div", {}, h("h4", {style: "margin:0 0 4px"}, "Voice"),
    !SR ? h("p", {class: "muted", style: "margin:4px 0"}, "Voice input is not available in this browser (Chrome and Safari support it).") : null,
    h("label", {style: "display:flex;gap:8px;align-items:flex-start;font-weight:400;margin:10px 0"}, speakBox, h("span", {}, "Read replies aloud" + (CAN_SPEAK ? "" : " (not available in this browser)"))),
    h("label", {style: "display:flex;gap:8px;align-items:flex-start;font-weight:400;margin:10px 0"}, handsBox, h("span", {}, "Hands-free conversation: after each spoken reply, listen again and send what I say.")),
    row("Voice language", lang, "Your phone's speech service does the listening and talking. On Chrome (Android) it is Google's, on iPhone it is Apple's, so your voice may leave your phone for that company. Nothing is recorded or kept by this app."),
    h("h4", {style: "margin:18px 0 4px"}, "How replies sound"),
    h("div", {style: "margin:8px 0"}, style, hint, custom, h("button", {class: "btn", style: "margin-top:8px", onclick: saveStyle}, "Save style")),
    h("small", {class: "muted", style: "display:block"}, "Your choice affects the replies you get. It only changes the style: safety rules, approvals and the sandbox stay exactly the same."),
    h("h4", {style: "margin:18px 0 4px"}, "Notifications"), h("div", {id: "push-row"}, pushRowInitial),
    h("h4", {style: "margin:18px 0 4px"}, "Time zone"), h("div", {id: "tz-row"}, tzRow(tzInfo)),
    h("h4", {style: "margin:18px 0 4px"}, "Appearance"), row("Theme", theme),
    h("h4", {style: "margin:18px 0 4px"}, "This app"),
    canInstall() ? h("button", {class: "btn", onclick: installApp}, "Install on this device") : h("p", {class: "muted", style: "margin:4px 0"}, IS_STANDALONE() ? "You are using the installed app." : "To install: use your browser's menu and choose “Install app” or “Add to Home screen”."),
    h("div", {style: "margin-top:12px"}, h("button", {class: "btn", onclick: () => { speak("Hello! This is how I sound."); }}, "Test voice")));
}

/* ---------- settings: web search ---------- */
async function searchPanel() {
  const d = await api("/api/search");
  const provider = h("select", {"aria-label": "Search provider"}, Object.entries(d.providers).map(([k, p]) => h("option", {value: k, selected: d.provider === k}, p.label)));
  const key = h("input", {type: "password", placeholder: d.configured ? "A key is saved. Paste a new one to replace it." : "Paste your search key", autocomplete: "off", "aria-label": "Search key"});
  const cap = h("input", {type: "number", min: 1, max: 1000, value: d.daily_cap, "aria-label": "Searches per day"});
  const note = h("small", {class: "muted", style: "display:block;margin-top:2px"}), out = h("div", {id: "search-test"});
  const showNote = () => { const p = d.providers[provider.value]; note.replaceChildren(p.note + " Get a key at ", h("a", {href: p.signup, target: "_blank", rel: "noopener"}, p.signup.replace("https://", ""))); };
  provider.onchange = showNote; showNote();
  const row = (label, el, n) => h("div", {style: "margin:12px 0"}, h("label", {style: "margin:0 0 4px"}, label), el, n || null);
  return h("div", {}, h("p", {style: "margin-top:0"}, "Agents can look things up on the web with your own search key. They get a few short snippets with their sources. They cannot open pages or download anything, and web text is treated as untrusted data, never as instructions."),
    h("div", {class: "card"}, d.configured ? "Search is on (" + d.providers[d.provider].label + "). Used today: " + d.used_today + " of " + d.daily_cap + "." : "Search is off. Add a key to turn it on."),
    row("Provider", provider, note), row("Key", key, h("small", {class: "muted", style: "display:block;margin-top:2px"}, "Stored in your keychain. It is never shown again, never sent to the model, and never included in exports.")),
    row("Searches per day", cap, h("small", {class: "muted", style: "display:block;margin-top:2px"}, "Stops runaway loops from using up your allowance.")),
    h("div", {style: "display:flex;gap:8px;flex-wrap:wrap"}, h("button", {class: "btn primary", onclick: async () => { const ok = await act(() => api("/api/search/settings", {provider: provider.value, key: key.value, daily_cap: +cap.value}), "Search settings saved"); if (ok) { key.value = ""; fill($("#settings-body"), await searchPanel()); } }}, "Save"),
      d.configured ? h("button", {class: "btn", onclick: async () => { try { const r = await api("/api/search/test", {query: "open source software"}); fill(out, r.results.length ? r.results.map((x) => h("div", {class: "card"}, h("strong", {}, x.title), h("div", {class: "muted", style: "font-size:13px"}, x.snippet), h("small", {}, x.url))) : h("p", {class: "muted"}, "The key works but the test found nothing.")); } catch (e) { toast(e.message, true); } }}, "Test search") : null,
      d.configured ? h("button", {class: "btn danger", onclick: () => confirmDialog("Remove the search key?", "Agents will no longer be able to search the web.", "Remove", async () => { await act(() => api("/api/search/remove", {}), "Key removed"); fill($("#settings-body"), await searchPanel()); })}, "Remove key") : null),
    out, h("p", {class: "muted", style: "font-size:13px;margin-top:14px"}, "Privacy: each search sends the words the agent chose to " + d.providers[d.provider].label + ". Secrets are never included, but think about what you ask. Search is counted and capped, and every search appears in the Log."));
}

/* ---------- settings: plugins ---------- */
function pluginPreview(info, source) {
  const names = agents().map((x) => x.name), picks = {};
  const boxes = names.map((n) => { const b = h("input", {type: "checkbox", "aria-label": "Switch on for " + n}); picks[n] = b; return h("label", {style: "display:flex;gap:8px;align-items:center;margin:4px 0"}, b, "Switch on for " + n); });
  const body = h("div", {}, h("p", {class: "muted", style: "margin:0 0 8px"}, "by " + info.author + " · version " + info.version + (info.already_installed ? " · replaces the installed copy" : "")), info.description ? h("p", {}, info.description) : null,
    info.hosts.length ? h("div", {class: "card"}, h("strong", {}, "It can contact: "), info.hosts.join(", "), h("div", {class: "muted", style: "font-size:13px"}, "Only these hosts, only through the guarded client, and only if the agent's Internet setting allows it.")) : h("div", {class: "card"}, "It makes no network calls."),
    info.secrets.length ? h("div", {class: "card"}, h("strong", {}, "It needs these secrets on the agent: "), info.secrets.join(", ")) : null,
    info.writes.length ? h("div", {class: "card"}, h("strong", {}, "Can send data out (needs your approval each time): "), info.writes.join(", ")) : null,
    info.skills.length ? h("div", {}, h("h4", {}, "Skills (read these: agents will follow this as guidance)"), info.skills.map((s) => h("div", {class: "card"}, h("strong", {}, s.name), h("pre", {class: "view", style: "margin-top:6px;white-space:pre-wrap"}, s.text)))) : null,
    info.tools.length ? h("div", {}, h("h4", {}, "Tools"), info.tools.map((t) => h("div", {class: "card"}, h("strong", {}, t.name), " ", h("code", {}, t.method + " " + t.url), h("div", {class: "muted", style: "font-size:13px"}, t.description)))) : null,
    h("h4", {}, "Fingerprint " + info.fingerprint), h("small", {class: "muted"}, "You approve exactly this. If the plugin changes, it will not install."), h("div", {style: "margin-top:10px"}, boxes));
  dialog("Install " + info.name + "?", null, body, (close) => [h("button", {class: "btn", onclick: close}, "Cancel"), h("button", {class: "btn primary", onclick: async () => {
    const ok = await act(() => api("/api/plugins/install", {...source, fingerprint: info.fingerprint, enable_for: names.filter((n) => picks[n].checked)}), "Plugin installed"); if (ok) { close(); const b = $("#settings-body"); if (b && S.settingsTab === "plugins") fill(b, await pluginsPanel()); } }}, "Install")]);
}
async function previewPlugin(source) { try { pluginPreview(await api("/api/plugins/preview", source), source); } catch (e) { toast(e.message, true); } }
async function pluginsPanel() {
  const d = await api("/api/plugins"), names = agents().map((x) => x.name);
  const list = d.plugins.length ? d.plugins.map((p) => h("div", {class: "card"}, h("div", {style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap"}, h("strong", {style: "flex:1"}, p.name + " " + p.version), h("span", {class: "muted", style: "font-size:13px"}, p.hosts.length ? "calls " + p.hosts.join(", ") : "no network"),
      h("button", {class: "btn danger", onclick: () => confirmDialog("Remove " + p.name + "?", "It stops working for every agent.", "Remove", async () => { await act(() => api("/api/plugins/uninstall", {id: p.id}), "Plugin removed"); fill($("#settings-body"), await pluginsPanel()); })}, "Remove")),
    h("div", {class: "muted", style: "font-size:13px"}, p.description || ""), h("div", {style: "display:flex;gap:6px;flex-wrap:wrap;margin-top:6px"}, names.map((n) => h("button", {class: "chip" + (p.enabled_for.includes(n) ? " on" : ""), "aria-pressed": p.enabled_for.includes(n),
      onclick: async () => { await act(() => api("/api/plugins/enable", {agent: n, id: p.id, on: !p.enabled_for.includes(n)}), n + (p.enabled_for.includes(n) ? ": off" : ": on")); fill($("#settings-body"), await pluginsPanel()); }}, n))))) : [h("div", {class: "card"}, "No plugins yet.")];
  const repo = h("input", {type: "text", placeholder: "owner/repository", "aria-label": "GitHub repository", autocapitalize: "none"});
  const paste = h("textarea", {rows: 5, placeholder: "{ \"id\": \"my-plugin\", ... }", "aria-label": "Plugin manifest"});
  return h("div", {}, h("p", {style: "margin-top:0"}, "Plugins add skills (instructions) and web-API tools to your agents. No plugin code runs on this server: a plugin can only read text and call the hosts it declares. You see everything before it installs, and it does nothing for an agent until you switch it on."),
    list, h("h4", {style: "margin:18px 0 6px"}, "Add a plugin"),
    h("div", {style: "display:flex;gap:8px"}, repo, h("button", {class: "btn primary", onclick: () => repo.value.trim() && previewPlugin({github: repo.value.trim()})}, "Preview")),
    h("small", {class: "muted", style: "display:block;margin:4px 0 10px"}, "A GitHub repository with a plugin.json at its top level. Only install plugins you trust: you are responsible for what they are told to do."),
    h("details", {}, h("summary", {style: "cursor:pointer"}, "Or paste a plugin.json"), paste, h("button", {class: "btn", style: "margin-top:6px", onclick: () => { try { previewPlugin({manifest: JSON.parse(paste.value)}); } catch (e) { toast("That is not valid JSON", true); } }}, "Preview")),
    h("h4", {style: "margin:18px 0 6px"}, "Examples"), h("div", {style: "display:flex;gap:8px;flex-wrap:wrap"}, Object.values(d.examples).map((x) => h("button", {class: "chip", onclick: () => previewPlugin({manifest: x})}, x.name))));
}

const NET_MODES = [["off", "Off", "This agent cannot use the internet."], ["ask", "Ask", "Every search or page fetch waits for your yes, showing exactly what it will look up."], ["allow", "Allow", "This agent may search and read public pages by itself."]];

/* ---------- settings: internet ---------- */
async function internetPanel() {
  const d = await api("/api/internet");
  const on = h("input", {type: "checkbox", checked: d.enabled, "aria-label": "Let agents use the internet"});
  const cap = h("input", {type: "number", min: 1, max: 1000, value: d.fetch_cap, "aria-label": "Page fetches per day"});
  return h("div", {}, h("p", {style: "margin-top:0"}, "You decide whether the AI can go online. Each agent has its own Off / Ask / Allow setting (open the agent's details). This switch overrides all of them."),
    h("label", {style: "display:flex;gap:10px;align-items:center;margin:12px 0"}, on, "Let agents use the internet at all"),
    h("div", {style: "margin:12px 0"}, h("label", {style: "margin:0 0 4px"}, "Page fetches per day"), cap, h("small", {class: "muted", style: "display:block;margin-top:2px"}, "Used today: " + d.fetched_today + ". Stops runaway loops.")),
    h("button", {class: "btn primary", onclick: async () => { const ok = await act(() => api("/api/internet", {enabled: on.checked, fetch_cap: +cap.value}), "Saved"); if (ok) fill($("#settings-body"), await internetPanel()); }}, "Save"),
    h("p", {class: "muted", style: "font-size:13px;margin-top:16px"}, "What agents can do online: read one public web page as text (never internal addresses, downloads or logins) and, with a key under Search, look things up. Web text is always treated as untrusted information, never as instructions, and every online action appears in the Log."));
}

/* ---------- settings: models (your own API key) ---------- */
const testResult = (r) => r.ok ? h("div", {class: "card"}, h("strong", {}, "Works. "), r.reply ? "The model said: " + r.reply : (r.note || ""), r.models.length ? h("div", {class: "muted", style: "font-size:13px;margin-top:4px"}, "Models you can use: " + r.models.slice(0, 40).join(", ")) : null) : h("div", {class: "card"}, "Problem: " + r.error);
async function modelsPanel() {
  const d = await api("/api/providers");
  const out = h("div", {id: "model-test"});
  const rows = d.profiles.map((p) => h("div", {class: "card"}, h("div", {style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap"},
    h("strong", {style: "flex:1"}, p.label + (p.default ? "  · default" : "")), h("span", {class: "muted", style: "font-size:13px"}, p.model || "no model chosen"),
    h("button", {class: "btn", onclick: async () => { try { fill(out, testResult(await api("/api/providers/test", {id: p.id}))); } catch (e) { toast(e.message, true); } }}, "Test"),
    p.default ? null : h("button", {class: "btn", onclick: async () => { await act(() => api("/api/providers/default", {id: p.id}), "Default changed"); fill($("#settings-body"), await modelsPanel()); }}, "Make default"),
    h("button", {class: "btn danger", onclick: () => confirmDialog("Remove " + p.label + "?", "Its saved key is deleted. Agents using it fall back to the default provider.", "Remove", async () => { await act(() => api("/api/providers/remove", {id: p.id}), "Provider removed"); fill($("#settings-body"), await modelsPanel()); })}, "Remove"))));
  const par = await api("/api/parallel");
  const limit = h("input", {type: "number", min: 1, max: par.max, value: par.limit, "aria-label": "Agents working at once", style: "max-width:90px"});
  const parallel = h("div", {class: "card"}, h("div", {style: "display:flex;gap:10px;align-items:center;flex-wrap:wrap"}, h("span", {style: "flex:1;min-width:180px"}, h("strong", {}, "Agents working at the same time"),
    h("div", {class: "muted", style: "font-size:13px"}, "Use @all to give every agent in a room the same task at once. Each one makes its own model calls, so more at once means faster work and faster spending (your daily cap still applies).")),
    limit, h("button", {class: "btn", onclick: () => act(() => api("/api/parallel", {limit: +limit.value}), "Saved")}, "Save")));
  const preset = h("select", {"aria-label": "Provider type"}, Object.entries(d.presets).map(([k, p]) => h("option", {value: k}, p.label)));
  const url = h("input", {type: "text", "aria-label": "Address", autocapitalize: "none", placeholder: "https://api.example.com/v1"});
  const key = h("input", {type: "password", "aria-label": "API key", autocomplete: "off", placeholder: "Paste your API key"});
  const model = h("input", {type: "text", "aria-label": "Model name", autocapitalize: "none", placeholder: "model name (you can test first to see a list)"});
  const kind = h("select", {"aria-label": "Kind"}, [["openai", "OpenAI-style API"], ["anthropic", "Anthropic (Claude)"], ["gemini", "Google Gemini"]].map(([v, l]) => h("option", {value: v}, l)));
  const note = h("small", {class: "muted", style: "display:block;margin-top:4px"});
  const fillPreset = () => { const p = d.presets[preset.value]; url.value = p.base_url; model.value = p.model; kind.value = p.kind; key.placeholder = p.keyless ? "No key needed for a model on this computer" : "Paste your API key";
    note.replaceChildren(p.signup ? h("span", {}, "Get a key at ", h("a", {href: p.signup, target: "_blank", rel: "noopener"}, p.signup.replace("https://", ""))) : "", " The model name is only a suggestion: use Test to see what your key can use."); };
  preset.onchange = fillPreset; fillPreset();
  const save = async () => { const p = d.presets[preset.value], id = preset.value === "custom" ? "custom-" + Math.random().toString(36).slice(2, 6) : preset.value;
    const ok = await act(() => api("/api/providers/save", {id, label: p.label, kind: kind.value, base_url: url.value, model: model.value, key: key.value, keyless: !!p.keyless, make_default: !d.profiles.length}), "Saved");
    if (ok) { key.value = ""; fill($("#settings-body"), await modelsPanel()); try { fill($("#model-test"), h("div", {class: "card"}, "Testing your key…")); fill($("#model-test"), testResult(await api("/api/providers/test", {id}))); } catch (e) { toast(e.message, true); } } };
  const row = (label, el) => h("div", {style: "margin:10px 0"}, h("label", {style: "margin:0 0 4px"}, label), el);
  return h("div", {}, h("p", {style: "margin-top:0"}, "This app runs on your own API key. Add any provider; agents use the default one unless you pick another for an agent. Your key is stored in your keychain, never shown again, and only ever sent to the address you enter here."),
    d.profiles.length ? rows : h("div", {class: "card"}, d.env_fallback ? "Using the key from this server's settings. Add a provider here to override it." : "No model is set up yet. Add one below to start."), out,
    parallel, h("h4", {style: "margin:18px 0 0"}, "Add a provider"), row("Service", preset), row("Address", url), kind, row("API key", key), row("Model", model), note,
    h("div", {style: "margin-top:12px"}, h("button", {class: "btn primary", onclick: save}, "Save")));
}

/* ---------- settings: backup ---------- */
async function backupPanel() {
  const d = await api("/api/backup");
  const when = (t) => new Date(t * 1000).toLocaleString();
  let state;
  if (!d.available) state = "Backups need an extra package on the server (pip install \"kintsugi[push]\").";
  else if (d.problem) state = "Backup settings need fixing: " + d.problem;
  else if (!d.configured) state = "Backups are off. Free hosts erase their disk when they restart, so turn this on if your data matters.";
  else if (d.running) state = "Backing up now…";
  else state = d.last ? (d.last.ok ? "Last backup: " + when(d.last.ts) + " (" + Math.max(1, Math.round(d.last.bytes / 1024)) + " KB, encrypted)." : "The last backup FAILED (" + when(d.last.ts) + "): " + d.last.error) : "Backups are on (to " + d.repo + "); none has run yet.";
  return h("div", {}, h("p", {style: "margin-top:0"}, "Your whole workspace is encrypted on the server with your passphrase, then saved to a private GitHub repository. If the server loses its disk, the backup comes back automatically at the next start. Lose the passphrase and nobody can read it, including us."),
    h("div", {class: "card"}, state),
    d.configured && d.available ? h("div", {style: "margin:12px 0"}, h("button", {class: "btn primary", disabled: d.running, onclick: async () => { await act(() => api("/api/backup/run", {}), "Backup started"); setTimeout(async () => fill($("#settings-body"), await backupPanel()), 2500); }}, "Back up now"), d.every_minutes ? h("small", {class: "muted", style: "margin-left:10px"}, "Also automatic, about every " + d.every_minutes + " minutes when something changed.") : null) : null,
    h("p", {class: "muted", style: "font-size:13px"}, "Set up on your hosting dashboard (never in this app): KINTSUGI_BACKUP_REPO (owner/private-repo), KINTSUGI_BACKUP_TOKEN (a fine-grained GitHub token for that one repo, Contents: read and write), KINTSUGI_BACKUP_PASSPHRASE (12+ characters). Steps are in docs/HOSTING.md. The access token is not included in backups."));
}

/* ---------- navigation ---------- */
function openRoom(name) {
  S.room = name; S.last[name] = 0; S.loadedRooms[name] = false; S.stick = true; S.sig = {}; closeSidebarMobile(); focusAgent();
  const ta = $("#msg"); if (ta) { ta.value = store.get("kt-draft-" + name) || ""; ta.dispatchEvent(new Event("input")); }
  poll(true);
}
async function dmWith(agent) {
  try { const r = await api("/api/dm", {a: "you", b: agent}); S.agent = agent; await poll(true); openRoom(r.room); } catch (e) { toast(e.message, true); }
}

/* ---------- drawer ---------- */
const TABS = [["agent", "Agent"], ["lessons", "Lessons"], ["files", "Files"], ["jobs", "Schedule"], ["apps", "Apps"], ["improve", "Improve"], ["safety", "Safety"], ["activity", "Log"]];
function toggleDrawer(force) {
  S.drawer = force === undefined ? !S.drawer : force; $("#drawer").hidden = !S.drawer; S.sig.drawer = null; S.sig.top = null;
  renderTopbar(true); if (S.drawer) poll(true);
}
async function loadTab() {
  const a = focusAgent(); if (!a || !S.drawer) return;
  const q = encodeURIComponent(a);
  if (S.tab === "agent") S.cache.plugins = (await api("/api/plugins")).plugins;
  if (S.tab === "lessons") S.cache.lessons = await api("/api/lessons?agent=" + q);
  if (S.tab === "files") S.cache.files = await api("/api/files?agent=" + q);
  if (S.tab === "improve") S.cache.improve = await api("/api/improve");
  if (S.tab === "activity") S.cache.activity = (await api("/api/audit")).filter((x) => x.agent === a).slice(-40).reverse();
}
function renderDrawer() {
  const d = $("#drawer"); if (!S.drawer) return;
  const a = agents().find((x) => x.name === focusAgent());
  const editing = d.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (editing) return;
  const data = {a, tab: S.tab, c: S.cache[S.tab], jobs: S.state.jobs, file: S.file, room: S.room, names: agents().map((x) => x.name), net: S.state.internet_enabled, prov: S.state.providers, pl: S.cache.plugins};
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
      h("h4", {}, "Internet"), h("div", {class: "seg", role: "group", "aria-label": "Internet access"}, NET_MODES.map(([m, label]) => h("button", {class: a.internet === m ? "on" : "", "aria-pressed": a.internet === m,
        onclick: () => act(() => api("/api/agent/internet", {agent: a.name, mode: m}), "Internet: " + label)}, label))),
      h("p", {class: "muted", style: "font-size:13px"}, NET_MODES.find((m) => m[0] === a.internet)[2] + (S.state.internet_enabled === false ? " (The workspace switch in Settings > Internet is OFF, so nothing goes online.)" : "")),
      h("h4", {}, "Plugins"), S.cache.plugins && S.cache.plugins.length ? h("div", {style: "display:flex;gap:6px;flex-wrap:wrap"}, S.cache.plugins.map((p) => h("button", {class: "chip" + ((a.plugins || []).includes(p.id) ? " on" : ""), "aria-pressed": (a.plugins || []).includes(p.id),
        onclick: () => act(() => api("/api/plugins/enable", {agent: a.name, id: p.id, on: !(a.plugins || []).includes(p.id)}), p.name + ((a.plugins || []).includes(p.id) ? ": off" : ": on"))}, p.name))) : h("p", {class: "muted", style: "font-size:13px"}, "No plugins installed. Add some in Settings > Plugins."),
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
  if (S.tab === "improve") return improveTab(a);
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
/* ---------- self-improvement ---------- */
const pct = (x) => Math.round((x || 0) * 100) + "%";
const CADENCES = [[0, "Never (only when I press a button)"], [1, "Every day"], [3, "Every 3 days"], [7, "Every week"], [14, "Every 2 weeks"], [30, "Every month"]];
function evidenceLine(p) {
  const e = p.evidence || {}, c = e.current || {}, d = e.candidate || {};
  return "Practice pass rate " + pct(c.pass_rate) + " → " + pct(d.pass_rate) + " · unsafe actions " + (c.violations || 0) + " → " + (d.violations || 0) + ". " + (e.note ? e.note.charAt(0).toUpperCase() + e.note.slice(1) + "." : "");
}
function proposalCard(p, showAgent) {
  const pending = p.status === "pending";
  return h("div", {class: "card"}, h("strong", {}, p.title), h("div", {class: "muted", style: "font-size:13px"}, evidenceLine(p)),
    p.kind === "playbook" ? h("pre", {class: "view", style: "margin-top:6px"}, p.detail) : h("div", {style: "margin-top:4px"}, "Model: ", h("code", {}, p.detail)),
    pending ? h("div", {style: "display:flex;gap:8px;margin-top:8px"}, h("button", {class: "btn primary", onclick: () => act(() => api("/api/improve/decide", {id: p.id, accept: true}), "Applied. You can undo it from the Improve tab."), }, "Accept"),
      h("button", {class: "btn", onclick: () => act(() => api("/api/improve/decide", {id: p.id, accept: false}), "Rejected")}, "Reject"))
      : h("small", {class: "muted"}, p.status + (p.decided_by ? " (" + p.decided_by + ")" : "")));
}
function improveTab(a) {
  const data = S.cache.improve;
  if (!data) return h("p", {class: "muted"}, "Loading…");
  const mine = data.proposals.filter((p) => p.agent === a.name), applied = (k) => mine.find((p) => p.status === "applied" && p.kind === k);
  const model = h("input", {type: "text", value: a.model || "", placeholder: "default model", "aria-label": "Model", autocapitalize: "none"});
  const provider = h("select", {"aria-label": "Provider"}, [h("option", {value: ""}, "Default provider")].concat((S.state.providers || []).map((p) => h("option", {value: p.id, selected: a.provider === p.id}, p.label + (p.default ? " (default)" : "")))));
  const playbook = h("textarea", {rows: 6, "aria-label": "Playbook", placeholder: "- Short rules this agent learned, one per line, each starting with a dash."}, a.playbook || "");
  return [h("p", {class: "muted"}, "The workspace tests " + a.name + " on practice tasks and proposes a better model or a better playbook. Only those two things can change; never permissions, code or secrets."),
    h("h4", {}, "Model"), h("div", {class: "stack"}, provider, model,
      h("div", {style: "display:flex;gap:8px;flex-wrap:wrap"}, h("button", {class: "btn", onclick: () => act(() => api("/api/agent/model", {agent: a.name, model: model.value.trim(), provider: provider.value}), "Model saved")}, "Save model"),
        applied("model") ? h("button", {class: "btn", onclick: () => act(() => api("/api/improve/revert", {agent: a.name, kind: "model"}), "Model change undone")}, "Undo the last improvement") : null)),
    h("h4", {}, "Playbook (rules in its prompt)"), h("div", {class: "stack"}, playbook,
      h("div", {style: "display:flex;gap:8px;flex-wrap:wrap"}, h("button", {class: "btn", onclick: () => act(() => api("/api/agent/playbook", {agent: a.name, playbook: playbook.value}), "Playbook saved")}, "Save playbook"),
        applied("playbook") ? h("button", {class: "btn", onclick: () => act(() => api("/api/improve/revert", {agent: a.name, kind: "playbook"}), "Playbook change undone")}, "Undo the last improvement") : null),
      h("small", {class: "muted"}, "Rules about permissions, secrets, links or safety are removed automatically, and a playbook never overrides the safety rules.")),
    h("h4", {}, "Proposals for " + a.name), mine.length ? mine.slice(0, 8).map((p) => proposalCard(p)) : h("p", {class: "muted"}, "Nothing yet. Run a study from Settings (the gear in the sidebar)."),
    h("button", {class: "btn", onclick: settingsDialog}, "Open self-improvement settings")];
}
async function improvePanel() {
  const data = await api("/api/improve"); S.improve = data;
  const st = data.settings;
  const cadence = h("select", {"aria-label": "Run automatically"}, CADENCES.map(([v, l]) => h("option", {value: v, selected: (st.enabled ? st.cadence_days : 0) === v}, l)));
  const calls = h("input", {type: "number", min: 20, max: 1000, value: st.max_calls, "aria-label": "Model calls per study"});
  const repeats = h("select", {"aria-label": "Repeats"}, [1, 2, 3, 4, 5].map((n) => h("option", {value: n, selected: st.repeats === n}, n + (n === 1 ? " time" : " times"))));
  const auto = h("input", {type: "checkbox", checked: st.auto_apply, style: "width:auto"});
  const share = h("input", {type: "checkbox", checked: st.share_lessons, style: "width:auto"});
  const cands = h("textarea", {rows: 3, placeholder: "One model name per line, e.g. qwen/qwen3.8-27b", "aria-label": "Models to test"}, st.candidates.join("\n"));
  const material = h("textarea", {rows: 4, placeholder: "Paste notes about other models, agent frameworks or techniques you want it to learn from.", "aria-label": "Study material"}, st.material);
  const found = h("div", {class: "chips", style: "justify-content:flex-start;margin-top:6px"});
  const save = async () => act(() => api("/api/improve/settings", {enabled: +cadence.value > 0, cadence_days: +cadence.value, max_calls: +calls.value, repeats: +repeats.value,
    auto_apply: auto.checked, share_lessons: share.checked, candidates: cands.value.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean), material: material.value}), "Settings saved");
  const run = async (kind) => { await save(); await act(() => api("/api/improve/run", {kind}), "Study started. It runs in the background."); loadImproveSections(); };
  const row = (label, el, note) => h("div", {style: "margin:12px 0"}, h("label", {style: "margin:0 0 4px"}, label), el, note ? h("small", {class: "muted", style: "display:block;margin-top:2px"}, note) : null);
  const content = h("div", {}, h("p", {style: "margin-top:0"}, "The workspace can test how well your agents use tools, try other models and tuning rules, and propose changes. It changes only which model an agent uses and its playbook, never permissions, code, secrets or the sandbox. Every change is shown with its evidence and can be undone."),
    h("h4", {style: "margin:14px 0 0"}, "Run a study"), h("div", {id: "imp-status", class: "muted"}), h("div", {style: "display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"},
      h("button", {class: "btn primary", onclick: () => run("all")}, "Run a full study"), h("button", {class: "btn", onclick: () => run("models")}, "Compare models only"), h("button", {class: "btn", onclick: () => run("playbooks")}, "Tune playbooks only")),
    h("small", {class: "muted", style: "display:block;margin-top:4px"}, "A study uses real model calls (up to the limit below) and counts against your daily cap. Its practice tasks are made up; none of your chats or files are used."),
    h("h4", {style: "margin:14px 0 0"}, "Needs your review"), h("div", {id: "imp-proposals"}), h("h4", {style: "margin:14px 0 0"}, "Recent studies"), h("div", {id: "imp-studies"}),
    h("h4", {style: "margin:18px 0 0"}, "Settings"),
    row("Run automatically", cadence), row("Limit per study", calls, "Model calls. A full study usually needs 100 to 200."), row("Repeat each practice task", repeats, "More repeats give steadier results and cost more."),
    row("Models to test against your current ones", cands, "Your provider's model names."), h("button", {class: "btn", style: "margin-top:-4px", onclick: async () => {
      try { const r = await api("/api/improve/models"); found.replaceChildren(...r.models.slice(0, 40).map((m) => h("button", {class: "chip", onclick: () => { cands.value = (cands.value.trim() ? cands.value.trim() + "\n" : "") + m; }}, m))); if (!r.models.length) toast("No model list available"); } catch (e) { toast(e.message, true); } }}, "Show models my key can use"), found,
    row("Study material (other models, other agent frameworks)", material, "Treated as untrusted notes. Rules about permissions, secrets or links are always removed. The workspace never browses the web by itself."),
    h("label", {style: "display:flex;gap:8px;align-items:flex-start;font-weight:400"}, auto, h("span", {}, "Apply clear wins automatically (a gain of at least 20 points on the practice tasks and no unsafe actions). Off means I review every change.")),
    h("label", {style: "display:flex;gap:8px;align-items:flex-start;font-weight:400"}, share, h("span", {}, "Also learn from each agent's own lessons. This sends those lessons to " + (S.state ? S.state.provider : "your model provider") + ".")),
    h("p", {class: "muted", style: "font-size:13px"}, "Honest limits: the practice suite is small, so differences of a few points are noise. It cannot prove an agent is better on your real work."));
  content.append(h("div", {style: "display:flex;justify-content:flex-end;margin-top:8px"}, h("button", {class: "btn primary", onclick: save}, "Save settings")));
  return content;
}
const SETTINGS_TABS = [["general", "General"], ["models", "Models"], ["internet", "Internet"], ["plugins", "Plugins"], ["search", "Search"], ["improve", "Improve"], ["backup", "Backup"]];
const SETTINGS_PANELS = {general: () => generalPanel(), search: () => searchPanel(), improve: () => improvePanel(), backup: () => backupPanel(), models: () => modelsPanel(), internet: () => internetPanel(), plugins: () => pluginsPanel()};
async function settingsDialog(tab) {
  if (typeof tab !== "string") tab = S.settingsTab || "general";
  S.settingsOpen = true;
  const body = h("div", {id: "settings-body"}), bar = h("div", {class: "tabs", role: "tablist", style: "padding:0;margin:0 0 12px"});
  const show = async (key) => {
    S.settingsTab = key;
    fill(bar, SETTINGS_TABS.map(([k, label]) => h("button", {class: "tab" + (k === key ? " on" : ""), role: "tab", "aria-selected": k === key, onclick: () => show(k)}, label)));
    fill(body, h("p", {class: "muted"}, "Loading…"));
    try { fill(body, await SETTINGS_PANELS[key]()); } catch (e) { fill(body, h("p", {class: "muted"}, e.message)); }
    if (key === "improve") renderImproveSections(S.improve);
  };
  const close = dialog("Settings", null, h("div", {}, bar, body), (c) => [h("button", {class: "btn primary", onclick: c}, "Done")], () => { S.settingsOpen = false; });
  close.dialog.style.width = "min(640px,100%)";
  await show(tab);
}
async function loadImproveSections() { try { S.improve = await api("/api/improve"); renderImproveSections(S.improve); } catch (e) { /* the poll shows connection problems */ } }
function renderImproveSections(d) {
  const status = $("#imp-status"), props = $("#imp-proposals"), studies = $("#imp-studies"); if (!status) return;
  const s = d.status, last = s.last;
  status.textContent = s.running ? "Studying now: " + (s.progress || "starting…") : last ? "Last study: " + new Date(last.ts * 1000).toLocaleString() + " (" + last.status + "; " + last.summary + ")" : "No study has run yet.";
  const pending = d.proposals.filter((p) => p.status === "pending");
  fill(props, pending.length ? pending.map((p) => proposalCard(p, true)) : h("p", {class: "muted", style: "margin:4px 0"}, "Nothing to review."));
  fill(studies, d.studies.length ? d.studies.slice(0, 5).map((x) => h("div", {class: "card", style: "display:flex;gap:8px;align-items:center"}, h("span", {style: "flex:1"}, "#" + x.id + " " + x.kind + " · " + x.status + " · " + x.summary),
    h("button", {class: "btn", onclick: async () => { try { const r = await api("/api/improve/study?id=" + x.id); dialog("Study #" + x.id, null, md(r.report), (c) => [h("button", {class: "btn", onclick: c}, "Close")]); } catch (e) { toast(e.message, true); } }}, "Report"))) : h("p", {class: "muted", style: "margin:4px 0"}, "None yet."));
}
async function viewFile(agent, path) { try { S.file = await api("/api/file?agent=" + encodeURIComponent(agent) + "&path=" + encodeURIComponent(path)); S.sig.drawer = null; renderDrawer(); } catch (e) { toast(e.message, true); } }

/* ---------- dialogs ---------- */
function dialog(title, desc, content, actions, onClose) {
  const root = $("#dialog-root");
  const close = () => { overlay.remove(); document.removeEventListener("keydown", esc); if (onClose) onClose(); };
  const esc = (e) => { if (e.key === "Escape" && root.lastElementChild === overlay) close(); };  // only the top dialog
  const overlay = h("div", {class: "overlay", onmousedown: (e) => { if (e.target === overlay) close(); }},
    h("div", {class: "dialog", role: "dialog", "aria-modal": "true", "aria-label": title}, h("h3", {}, title), desc ? h("p", {}, desc) : null, content,
      actions ? h("div", {class: "actions"}, actions(close)) : null));
  document.addEventListener("keydown", esc);
  root.append(overlay);
  const first = overlay.querySelector("input,textarea,select"); if (first) first.focus();
  close.dialog = overlay.querySelector(".dialog");
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
    focusAgent(); syncUnread(); renderSidebar(); renderTopbar(); updateComposer();
    if (S.state.model_ready === false && !S.askedModel && !S.settingsOpen && !$("#dialog-root .dialog")) { S.askedModel = true; settingsDialog("models"); }
    if (S.room) {
      const after = S.last[S.room] || 0, fresh = await api("/api/messages?room=" + encodeURIComponent(S.room) + "&after=" + after);
      const msgs = fresh.filter((m) => m.id > after);
      if (msgs.length) S.last[S.room] = msgs[msgs.length - 1].id;
      const wasLoaded = !!S.loadedRooms[S.room];
      renderThread(msgs);
      S.loadedRooms[S.room] = true;
      if (wasLoaded) maybeSpeak(msgs);  // never read the backlog aloud, only what arrives while you are here
    } else renderThread([]);
    renderInline();
    if (S.drawer) { await loadTab(); renderDrawer(); }
    if (S.settingsOpen) await loadImproveSections();
    if (S.wantNew && S.state) { S.wantNew = false; newChatDialog(); }
    $("#main").classList.remove("offline");
  } catch (e) {
    if (!/access token/.test(e.message)) toast(e.message === "Failed to fetch" ? "Can't reach the workspace. Retrying…" : e.message, true);
    if (!S.state && !/access token/.test(e.message)) fill($("#thread"), h("div", {class: "hello"}, h("img", {src: "/static/logo.svg", alt: ""}),
      h("h2", {}, navigator.onLine ? "Can't reach your workspace" : "You're offline"), h("p", {}, "Your chats are safe on your server. They will appear as soon as the connection is back.")));
  }
  finally {
    polling = false;
    if (again) { again = false; poll(); return; }
    const busy = (S.state && S.state.busy.length > 0) || S.fast > 0;
    if (S.fast > 0) S.fast--;
    timer = setTimeout(poll, document.hidden ? 8000 : busy ? 800 : 2500);
  }
}

/* ---------- start ---------- */
function setupMobile() {
  syncVoiceButtons();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => { /* private mode or unsupported: the app works without it */ });
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); S.installEvent = e; S.sig.side = null; renderSidebar(); });
  window.addEventListener("appinstalled", () => { S.installEvent = null; S.sig.side = null; renderSidebar(); toast("Installed. Open it from your home screen."); });
  window.addEventListener("offline", () => toast("You're offline. The app will catch up when you're back.", true));
  window.addEventListener("online", () => { toast("Back online"); poll(true); });
  // keep the composer above the on-screen keyboard (iOS does not shrink the layout viewport)
  if (window.visualViewport) {
    const fit = () => { $("#app").style.height = matchMedia("(max-width:860px)").matches ? visualViewport.height + "px" : ""; if (matchMedia("(max-width:860px)").matches) window.scrollTo(0, 0); };
    visualViewport.addEventListener("resize", fit); visualViewport.addEventListener("scroll", fit); fit();
  }
  // swipe in from the left edge to open the sidebar, swipe left on it to close
  let sx = 0, sy = 0, tracking = "";
  document.addEventListener("touchstart", (e) => { const t = e.touches[0]; sx = t.clientX; sy = t.clientY; tracking = sx < 24 ? "open" : $("#app").classList.contains("open") ? "close" : ""; }, {passive: true});
  document.addEventListener("touchend", (e) => {
    if (!tracking || !matchMedia("(max-width:860px)").matches) return;
    const t = e.changedTouches[0], dx = t.clientX - sx, dy = Math.abs(t.clientY - sy);
    if (tracking === "open" && dx > 70 && dy < 50 && !$("#app").classList.contains("open")) toggleSidebar();
    if (tracking === "close" && dx < -70 && dy < 50) closeSidebarMobile();
    tracking = "";
  }, {passive: true});
}
function init() {
  applyTheme();
  setupMobile();
  if (new URLSearchParams(location.search).get("action") === "new") { S.wantNew = true; history.replaceState(null, "", location.pathname + location.hash); }
  const m = location.hash.match(/token=([^&]+)/);
  if (m) { S.token = decodeURIComponent(m[1]); store.set("kt-token", S.token); history.replaceState(null, "", location.pathname); }
  else S.token = store.get("kt-token") || "";
  if (store.get("kt-collapsed")) $("#app").classList.add("collapsed");
  $("#scrim").addEventListener("click", closeSidebarMobile);
  $("#scroll").addEventListener("scroll", () => { const s = $("#scroll"); if (s.scrollHeight - s.scrollTop - s.clientHeight < 90) $("#jump").hidden = true; }, {passive: true});
  $("#jump").addEventListener("click", () => { const s = $("#scroll"); s.scrollTop = s.scrollHeight; $("#jump").hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#dialog-root .dialog")) { if (S.drawer) toggleDrawer(false); closeSidebarMobile(); } });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { syncUnread(); poll(true); } });
  buildComposer(); syncVoiceButtons(); $("#sidebar").replaceChildren(h("div", {class: "brand"}, h("img", {src: "/static/logo.svg", alt: ""}), "Kintsugi"));
  poll(true);
}
init();
