// AI Office · Лев: мінімальний service worker. Дані завжди з мережі (ціни й угоди не кешуються); оболонка сторінки — з мережі, а без звʼязку з кешу.
const SHELL = 'lev-shell-v13';
self.addEventListener('install', e => { self.skipWaiting(); e.waitUntil(caches.open(SHELL).then(c => c.addAll(['/lev/', '/lev/icon-192.png']).catch(() => {}))); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.pathname.startsWith('/api/')) return;
  if (u.origin === location.origin && u.pathname.startsWith('/lev')) e.respondWith(fetch(e.request).then(r => { const cp = r.clone(); caches.open(SHELL).then(c => c.put(e.request, cp)).catch(() => {}); return r; }).catch(() => caches.match(e.request).then(m => m || caches.match('/lev/'))));
});
