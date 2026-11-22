// Datos: siempre de la red (con respaldo en caché si no hay internet, marcado con X-Desde-Cache). App: red primero, caché de respaldo.
const C = "picks-v3";
const SHELL = ["./", "index.html", "app.js", "manifest.webmanifest", "icon.svg", "icon-192.png", "icon-512.png", "icon-512-maskable.png", "apple-touch-icon.png"];
self.addEventListener("install", e => e.waitUntil(
  caches.open(C).then(c => c.addAll(SHELL.map(u => new Request(u, {cache: "no-cache"})))).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
function marcar(r) {   // respuesta desde caché: la UI avisa "Modo sin conexión"
  const h = new Headers(r.headers); h.set("X-Desde-Cache", "1");
  return new Response(r.body, {status: r.status, statusText: r.statusText, headers: h});
}
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  if (u.pathname.includes("/data/")) {
    e.respondWith(fetch(e.request, {cache: "no-store"}).then(r => { if (r.ok) { const k = r.clone(); caches.open(C).then(c => c.put(u.pathname, k)); } return r; })
      .catch(() => caches.match(u.pathname).then(m => m ? marcar(m) : Response.error())));
  } else {
    e.respondWith(fetch(e.request, {cache: "no-cache"}).then(r => { if (r.ok) { const k = r.clone(); caches.open(C).then(c => c.put(e.request, k)); } return r; })
      .catch(() => caches.match(e.request).then(m => m || caches.match("./"))));
  }
});
