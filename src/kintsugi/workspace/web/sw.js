/* Kintsugi service worker: makes the app installable and lets its shell open offline.
   It NEVER caches /api/* or /apps/* (they carry your data) and never stores the access token. */
const VERSION = "__VERSION__";
const CACHE = "kintsugi-shell-" + VERSION;
const SHELL = ["/", "/static/app.css", "/static/app.js", "/static/extras.js", "/static/logo.svg", "/static/vendor/marked.min.js",
               "/static/vendor/purify.min.js", "/static/icons/icon-192.png", "/static/icons/icon-512.png", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k.startsWith("kintsugi-shell-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request, url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/apps/") || url.pathname === "/healthz") return;  // network only, never cached
  if (req.mode === "navigate") {  // the page: fresh when online, the cached shell when offline
    event.respondWith(fetch(req).catch(() => caches.match("/")));
    return;
  }
  event.respondWith(caches.match(req).then((hit) => {
    const fresh = fetch(req).then((res) => { if (res.ok) caches.open(CACHE).then((c) => c.put(req, res.clone())); return res; }).catch(() => hit);
    return hit || fresh;
  }));
});

/* Push notifications carry no message text (privacy): they only say that something new is waiting. */
self.addEventListener("push", (event) => {
  event.waitUntil(self.registration.showNotification("Kintsugi", {
    body: "You have something new.", icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png", tag: "kintsugi-new", renotify: false,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then((list) => {
    for (const client of list) { if ("focus" in client) return client.focus(); }
    return self.clients.openWindow("/");
  }));
});
