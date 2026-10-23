/* Only the explicit, public foundation resources may enter Cache Storage. */
const CACHE_PREFIX = 'motionmate-pwa-';
const CACHE_NAME = CACHE_PREFIX + '__PWA_VERSION__';
const SHELL_URLS = {{ assets_json|safe }}.map(url => new URL(url, self.location.origin).href);
const OFFLINE_URL = new URL({{ offline_json|safe }}, self.location.origin).href;
const SCOPE_PATH = {{ scope_json|safe }};
const TRACKING_PATH = {{ tracking_json|safe }};
const STATIC_PATH = new URL({{ static_json|safe }}, self.location.origin).pathname;

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    // Anonymous fetches only. Redirects/errors cannot poison the offline shell.
    for (const url of SHELL_URLS) {
      const response = await fetch(url, { cache: 'no-store', credentials: 'omit' });
      if (!response.ok || response.redirected || response.type === 'opaque') {
        throw new Error('Motionmate offline shell unavailable');
      }
      await cache.put(url, response);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.method === 'GET' && SHELL_URLS.includes(url.href)) {
    event.respondWith((async () => {
      const cache = await caches.open(CACHE_NAME);
      return (await cache.match(request)) || fetch(request, { cache: 'no-store' });
    })());
    return;
  }

  // Other static files retain WhiteNoise/browser caching, without entering
  // our persistent cache. Do not override the existing hashed asset pipeline.
  if (request.method === 'GET' && url.pathname.startsWith(STATIC_PATH)) return;

  // Never read/write an operational response in Cache Storage or HTTP cache.
  // Mutations and API failures reject normally; there is no queue or retry.
  const appNavigation = request.method === 'GET' && request.mode === 'navigate' &&
    ['accounts/', 'crm/', 'businesses/', 'appointments/', 'billings/', 'billing/',
      'logistics/parcels/', 'logistics/shipments/']
      .some(path => url.pathname.startsWith(SCOPE_PATH + path)) &&
    url.pathname !== TRACKING_PATH;
  event.respondWith(fetch(request, { cache: 'no-store' }).catch(async error => {
    if (!appNavigation) throw error;
    const cache = await caches.open(CACHE_NAME);
    const fallback = await cache.match(OFFLINE_URL);
    if (!fallback) throw error;
    return new Response(await fallback.text(), {
      status: 503,
      headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' }
    });
  }));
});
