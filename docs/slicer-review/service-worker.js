/* SPDX-License-Identifier: GPL-3.0-or-later
 * Cache only this application's explicit static resources, never user evidence.
 */
const PREFIX = 'klipperlearn-slicer-review-shell-';
const CACHE = PREFIX + '0.1.0';
const FILES = ['index.html','help.html','app.js','engine.js','sample.js','style.css',
  'install.js','manifest.webmanifest','COPYING','assets/adjustment-card.stl',
  'icons/icon-16.png','icons/icon-32.png','icons/icon-48.png','icons/icon-128.png',
  'icons/icon-192.png','icons/icon-512.png'];
const allowed = new Set(FILES.map(file => new URL(file,self.registration.scope).href));
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache =>
  cache.addAll(FILES.map(file => new Request(new URL(file,self.registration.scope), {cache:'reload'}))))));
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith(PREFIX) && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.search) return;
  if (url.href === self.registration.scope) url.pathname += 'index.html';
  if (!allowed.has(url.href)) return;
  event.respondWith(caches.open(CACHE).then(async cache => {
    const saved = await cache.match(url.href);
    return saved || fetch(event.request);
  }));
});
