const CACHE_PREFIX = "klipperlearn-mobile-";
const CACHE = "klipperlearn-mobile-console-v051";
const ASSETS = [
  "./", "index.html", "console.html", "console.css?ui=10", "console-shell.js?v=5",
  "trial-telemetry.js?v=3", "photo-pair.js?v=2", "telemetry-outbox.js?v=1",
  "device-owner.js?v=1", "console.js?v=25", "calibration-workflow.js?v=7", "review.js?v=6", "manifest.webmanifest",
  "icon.svg", "klipper-logo.svg", "printer-cameras.js?v=1", "learning-status.js?v=3"
];
const SCOPE = new URL(self.registration.scope);
const API_PATH = new URL("api/", SCOPE).pathname;
const API_ROOT = API_PATH.endsWith("/") ? API_PATH.slice(0, -1) : API_PATH;

function isCacheableAsset(request) {
  if (request.method !== "GET") return false;
  const url = new URL(request.url);
  return (
    url.origin === self.location.origin &&
    url.pathname.startsWith(SCOPE.pathname) &&
    url.pathname !== API_ROOT &&
    !url.pathname.startsWith(API_PATH) &&
    !["authorization", "cookie", "x-klipperlearn-token", "x-klipperlearn-viewer"].some((name) =>
      request.headers.has(name)
    )
  );
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw error;
  }
}

self.addEventListener("install", (event) => event.waitUntil(
  caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
));
self.addEventListener("activate", (event) =>
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
      .then(() => self.clients.matchAll({type: "window", includeUncontrolled: true}))
      .then((clients) => Promise.all(clients.map(async (client) => {
        const url = new URL(client.url);
        if (url.origin === SCOPE.origin && [SCOPE.pathname, SCOPE.pathname + "index.html", SCOPE.pathname + "console.html", SCOPE.pathname + "history.html"].includes(url.pathname)) {
          // Do not reload the current UI underneath an active permission prompt.
          const current = await new Promise(resolve => {
            const channel = new MessageChannel();
            const finish = value => { clearTimeout(timer); channel.port1.close(); resolve(value); };
            const timer = setTimeout(() => finish(false), 1500);
            channel.port1.onmessage = event => finish(event.data === '25');
            client.postMessage({type: 'klipperlearn:version'}, [channel.port2]);
          });
          if (current) return;
          const destination = new URL("console.html", SCOPE);
          destination.searchParams.set("ui", "25");
          return client.navigate(destination.href);
        }
      })))
  )
);
self.addEventListener("fetch", (event) => {
  if (!isCacheableAsset(event.request)) return;
  event.respondWith(networkFirst(event.request));
});
