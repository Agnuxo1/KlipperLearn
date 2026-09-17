/* SPDX-License-Identifier: GPL-3.0-or-later */
let deferred = null;
const offline = document.getElementById('enable-offline');
const install = document.getElementById('install-app');
const status = document.getElementById('install-status');
window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault(); deferred = event; install.hidden = false;
});
window.addEventListener('appinstalled', () => {
  install.hidden = true; deferred = null;
  status.textContent = 'App installed. Save sessions explicitly; user files are not persisted.';
});
offline.addEventListener('click', async () => {
  offline.disabled = true;
  try {
    if (!isSecureContext || !('serviceWorker' in navigator)) throw new Error('HTTPS and service-worker support are required.');
    await navigator.serviceWorker.register('service-worker.js', {scope:'./'});
    await navigator.serviceWorker.ready;
    status.textContent = 'Offline application files are ready. Use Install app or your browser menu to add this app. Save sessions before closing.';
  } catch (error) { status.textContent = error.message; offline.disabled = false; }
});
install.addEventListener('click', async () => {
  if (!deferred) return;
  await deferred.prompt(); await deferred.userChoice;
  deferred = null; install.hidden = true;
});
