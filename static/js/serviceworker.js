const CACHE_NAME = 'ristobar-v2';
const CACHE_URLS = ['/', '/static/css/style.css', '/static/js/app.js'];

// Prefissi da NON intercettare (admin Django, API, webhook)
const BYPASS = ['/amministrazione/', '/api/', '/webhooks/'];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(CACHE_URLS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Lascia passare direttamente le URL escluse
    if (BYPASS.some(prefix => url.pathname.startsWith(prefix))) {
        return;
    }

    // Solo GET — lascia passare POST/PUT/DELETE senza cache
    if (event.request.method !== 'GET') {
        return;
    }

    event.respondWith(
        caches.match(event.request).then(cached => {
            return cached || fetch(event.request).catch(() => {
                // Rete non disponibile: risposta vuota invece di errore
                return new Response('', { status: 503, statusText: 'Offline' });
            });
        })
    );
});
