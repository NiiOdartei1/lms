const CACHE_NAME = "teacher-lms-v1";

self.addEventListener("install", event => {
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);

  if (!url.pathname.startsWith("/teacher/")) return;

  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});
