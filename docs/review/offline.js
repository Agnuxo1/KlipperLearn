/* SPDX-License-Identifier: MIT
 * Opt-in PWA shell caching only. No loaded file is sent to a worker or server.
 */
(function () {
  'use strict';
  if (!/^https?:$/.test(location.protocol) || !('serviceWorker' in navigator)) return;
  const section = document.getElementById('offline-section');
  const enable = document.getElementById('offline-enable');
  const disable = document.getElementById('offline-disable');
  const status = document.getElementById('offline-status');
  const scope = new URL('./', location.href).href;
  section.hidden = false;
  enable.addEventListener('click', async () => {
    enable.disabled = true;
    try {
      await navigator.serviceWorker.register('service-worker.js', {scope: './', updateViaCache: 'none'});
      let timer;
      try {
        await Promise.race([navigator.serviceWorker.ready,
          new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('Offline setup timed out; reload and retry.')), 15000); })]);
      } finally { clearTimeout(timer); }
      disable.hidden = false;
      status.textContent = 'Offline shell ready. Install from the browser menu where supported. Sessions are never cached; save them before closing.';
    } catch (error) { status.textContent = 'Offline setup unavailable: ' + error.message; }
    finally { enable.disabled = false; }
  });
  disable.addEventListener('click', async () => {
    disable.disabled = true;
    try {
      const registrations = await navigator.serviceWorker.getRegistrations();
      for (const registration of registrations) if (registration.scope === scope) await registration.unregister();
      for (const key of await caches.keys()) if (key.startsWith('klipperlearn-review-shell-')) await caches.delete(key);
      status.textContent = 'Offline copy removed. Close this page to finish; saved files on your disk are unchanged.';
      disable.hidden = true;
    } catch (error) { status.textContent = 'Could not remove offline copy: ' + error.message; }
    finally { disable.disabled = false; }
  });
  navigator.serviceWorker.getRegistration(scope).then(registration => {
    if (registration && registration.scope === scope) disable.hidden = false;
  }).catch(() => {});
}());
