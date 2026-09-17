/* SPDX-License-Identifier: MIT. Cache public shell files only, never input data. */
'use strict';
const CACHE = 'klipperlearn-review-shell-e4e506016737';
const SHELL = ["index.html", "style.css", "core.js", "demo.js", "strict-json.js", "review.js", "offline.js", "privacy.html", "manifest.webmanifest", "icons/icon128.png", "icons/icon192.png", "icons/icon512.png", "LICENSE.txt"];
const allowed = new Set(SHELL.map(name => new URL(name, self.registration.scope).href));
self.addEventListener('install', event => event.waitUntil((async () => {
  const cache = await caches.open(CACHE);
  await cache.addAll([...allowed]);
  await self.skipWaiting();
})()));
self.addEventListener('activate', event => event.waitUntil((async () => {
  for (const key of await caches.keys()) if (key.startsWith('klipperlearn-review-shell-') && key !== CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  let url = new URL(event.request.url);
  if (url.href === self.registration.scope) url = new URL('index.html', self.registration.scope);
  if (!allowed.has(url.href)) return;
  event.respondWith((async () => (await caches.open(CACHE)).match(url.href).then(hit => hit || fetch(event.request)))());
});
