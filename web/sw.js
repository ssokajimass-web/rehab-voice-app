// Service Worker for リハ・アシスト
const CACHE_NAME = 'rehab-voice-app-v5';

const STATIC_ASSETS = [
  './',
  './index.html',
  './style.css',
  './app.js',
  './rehab_config.json',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon.svg',
  './audio/voice_timeline.json',
  './audio/arm_timeline.json',
  './audio/leg_timeline.json',
  './audio/breathing_timeline.json'
];

// インストール時に静的アセットをキャッシュ
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    }).then(() => self.skipWaiting())
  );
});

// アクティベート時に古いキャッシュを削除
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// フェッチ処理（Cache-First + ネットワークフォールバック）
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Rangeリクエスト（音声再生のシークなど）の場合はブラウザに直接任せるかキャッシュから取得
  if (event.request.headers.has('range')) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        return cachedResponse;
      }
      return fetch(event.request).then((networkResponse) => {
        // 音声ファイルやJSONなら動的キャッシュに追加
        if (
          networkResponse.status === 200 &&
          (url.pathname.endsWith('.mp3') || url.pathname.endsWith('.json'))
        ) {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return networkResponse;
      });
    })
  );
});
