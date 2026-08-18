{% load static %}

{% if debug_mode %}
const CACHE_PREFIX = 'insights-pwa-';

self.addEventListener('install', function (event) {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (key) {
        return key.indexOf(CACHE_PREFIX) === 0;
      }).map(function (key) {
        return caches.delete(key);
      }));
    }).then(function () {
      return self.clients.claim();
    }).then(function () {
      return self.registration.unregister();
    })
  );
});

self.addEventListener('fetch', function (event) {
  event.respondWith(fetch(event.request));
});
{% else %}
const CACHE_NAME = '{{ cache_name }}';
const OFFLINE_URL = '{% url "offline" %}';

const APP_SHELL = [
  '{% url "home" %}',
  '{% url "services" %}',
  '{% url "contact_support" %}',
  '{% url "login" %}',
  '{% url "signup" %}',
  '{% url "webmanifest" %}',
  OFFLINE_URL,
  '{% static "css/tailwind-build.css" %}',
  '{% static "css/base.css" %}',
  '{% static "css/home.css" %}',
  '{% static "css/services.css" %}',
  '{% static "css/contact.css" %}?v=4',
  '{% static "css/auth.css" %}',
  '{% static "css/offline.css" %}',
  '{% static "js/base.js" %}',
  '{% static "js/home.js" %}',
  '{% static "pwa/icon-32.png" %}',
  '{% static "pwa/icon-180.png" %}',
  '{% static "pwa/icon-192.png" %}',
  '{% static "pwa/icon-512.png" %}',
  '{% static "pwa/icon-maskable-192.png" %}',
  '{% static "pwa/icon-maskable-512.png" %}',
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(APP_SHELL);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (key) {
          return key !== CACHE_NAME;
        }).map(function (key) {
          return caches.delete(key);
        })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (event) {
  if (event.request.method !== 'GET') {
    return;
  }

  const requestUrl = new URL(event.request.url);
  const isSameOrigin = requestUrl.origin === self.location.origin;

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then(function (response) {
        const responseClone = response.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, responseClone);
        });
        return response;
      }).catch(function () {
        return caches.match(event.request).then(function (cachedResponse) {
          return cachedResponse || caches.match(OFFLINE_URL);
        });
      })
    );
    return;
  }

  if (!isSameOrigin) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(function (cachedResponse) {
      if (cachedResponse) {
        fetch(event.request).then(function (networkResponse) {
          if (!networkResponse || networkResponse.status !== 200) {
            return;
          }
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(event.request, networkResponse.clone());
          });
        }).catch(function () {
          return undefined;
        });
        return cachedResponse;
      }

      return fetch(event.request).then(function (networkResponse) {
        if (!networkResponse || networkResponse.status !== 200) {
          return networkResponse;
        }

        const responseClone = networkResponse.clone();
        caches.open(CACHE_NAME).then(function (cache) {
          cache.put(event.request, responseClone);
        });
        return networkResponse;
      });
    })
  );
});
{% endif %}
