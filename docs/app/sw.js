// SPDX-License-Identifier: GPL-3.0-or-later
// Offline app shell. Only public application files are cached; user data lives in IndexedDB.
const CACHE = 'klipperlearn-phone-v1';
const SHELL = ['./', 'index.html', 'app.css', 'manifest.webmanifest', 'icon.svg',
  'js/main.js', 'js/i18n.js', 'js/connection.js', 'js/usb-drivers.js', 'js/printer.js', 'js/simulator.js',
  'js/gcode-transform.js', 'js/calibration.js', 'js/analysis.js', 'js/advisor.js', 'js/store.js',
  'js/jev-client.js', 'js/sensors.js'];

self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
// Network first so updates arrive when online; cache as the offline fallback.
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(res => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return res;
  }).catch(() => caches.match(e.request, {ignoreSearch: true}).then(r => r || caches.match('index.html'))));
});
