// Network-first: always try fresh data; fall back to cache when offline.
const C = "nflbets-v2";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  e.respondWith(fetch(e.request).then(r => { const cp = r.clone(); caches.open(C).then(c => c.put(e.request.url.split("?")[0], cp)); return r; })
    .catch(() => caches.match(e.request.url.split("?")[0])));
});
