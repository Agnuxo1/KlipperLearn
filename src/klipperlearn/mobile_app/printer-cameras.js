/* Configured printer views use the same connection as the console. No new permissions. */
(() => {
  'use strict';
  const host = document.getElementById('printerCameras');
  let timer = null, busy = false, views = [];
  function token() {
    try { return localStorage.getItem('klipperlearn-token') || sessionStorage.getItem('klipperlearn-token') || ''; }
    catch (_) { return ''; }
  }
  async function request(path) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch('/mobile/api/printer/cameras' + path, {
        cache: 'no-store', signal: controller.signal, headers: {'X-KlipperLearn-Token': token()}
      });
      if (!response.ok) throw Error("No recent image");
      return path ? response.blob() : (await response.json()).result;
    } finally { clearTimeout(timeout); }
  }
  function makeView(camera) {
    const figure = document.createElement('figure'), img = document.createElement('img'), caption = document.createElement('figcaption');
    figure.className = 'printer-camera'; img.alt = camera.name; caption.textContent = camera.name + ' · conectando';
    figure.append(img, caption); host.append(figure);
    return {camera, img, caption, url: null};
  }
  async function refresh() {
    clearTimeout(timer);
    if (busy || document.hidden || document.getElementById('view-camera').hidden || !token()) return;
    busy = true;
    try {
      if (!views.length) {
        const cameras = await request('');
        views = (Array.isArray(cameras) ? cameras : []).map(makeView);
        host.hidden = !views.length;
      }
      await Promise.all(views.map(async view => {
        try {
          const blob = await request('/' + encodeURIComponent(view.camera.id) + '/snapshot');
          if (view.url) URL.revokeObjectURL(view.url);
          view.url = URL.createObjectURL(blob); view.img.src = view.url;
          await view.img.decode();
          const angle = [0, 90, 180, 270].includes(view.camera.rotation) ? view.camera.rotation : 0;
          const rect = view.img.parentElement.getBoundingClientRect(), sideways = angle % 180 !== 0;
          Object.assign(view.img.style, {position: 'absolute', left: '50%', top: '50%',
            width: (sideways ? rect.height : rect.width) + 'px', height: (sideways ? rect.width : rect.height) + 'px',
            transform: 'translate(-50%, -50%) rotate(' + angle + 'deg)'});
          view.caption.textContent = view.camera.name + ' · ahora';
        } catch (_) {
          view.img.removeAttribute('src');
          view.caption.textContent = view.camera.name + " · no recent image";
        }
      }));
    } catch (_) { /* Printer controls remain independent. */ }
    finally { busy = false; timer = setTimeout(refresh, 3000); }
  }
  document.addEventListener('console:view', event => { if (event.detail === 'camera') void refresh(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) void refresh(); });
  window.addEventListener('pagehide', () => { clearTimeout(timer); views.forEach(view => { if (view.url) URL.revokeObjectURL(view.url); }); });
})();
