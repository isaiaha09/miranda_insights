{% load static %}

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
  '{% static "css/contact.css" %}',
  '{% static "css/auth.css" %}',
  '{% static "css/offline.css" %}',
  '{% static "js/base.js" %}',
  '{% static "js/home.js" %}',
  '{% static "favicon.svg" %}',
  '{% static "pwa/icon-180.png" %}',
  '{% static "pwa/icon-192.png" %}',
  '{% static "pwa/icon-512.png" %}',
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