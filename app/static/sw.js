/* Qonunnoma service worker: ilovani bosh ekranga o'rnatish va tez ochish uchun.
   Savol-javob, kirish va boshqa API so'rovlari HECH QACHON keshlanmaydi. */
const CACHE = 'qonunnoma-v1';
const SHELL = ['/app', '/static/logo.svg', '/static/icon-192.png', '/static/icon-512.png', '/static/apple-touch-icon.png'];
const API = /^\/(auth|chat|me|admin|v1|ingest|documents|search|ask|health|feedback|openapi)(\/|$)/;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || API.test(url.pathname)) return;

  if (req.mode === 'navigate') {
    // Sahifa: avval tarmoq (yangilangan nusxa), internet yo'q bo'lsa — keshdagi
    e.respondWith(
      fetch(req).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
      }).catch(() => caches.match(req).then(hit => hit || caches.match('/app')))
    );
    return;
  }

  if (url.pathname.startsWith('/static/')) {
    // Rasm va ikonkalar: keshdan darrov, fonda yangilanadi
    e.respondWith(
      caches.match(req).then(hit => {
        const fresh = fetch(req).then(res => {
          if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
          return res;
        }).catch(() => hit);
        return hit || fresh;
      })
    );
  }
});
