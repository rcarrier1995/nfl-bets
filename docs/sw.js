// Network-first and never from the browser's HTTP cache, so a new version shows on the next open.
// The offline copy is only used when there is no connection.
const C = "nflbets-v3";
self.addEventListener("install", e => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  const key = e.request.url.split("?")[0];
  e.respondWith(fetch(e.request, { cache: "no-store" })
    .then(r => { if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(key, cp)); } return r; })
    .catch(() => caches.match(key)));
});
