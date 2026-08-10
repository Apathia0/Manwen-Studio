/* StoryCanvas Service Worker — 零依赖手写实现
 * 策略：
 *  - 预缓存：应用外壳关键资源（图标、manifest、字体样式等）
 *  - 运行时缓存：/assets/ 下带内容哈希的构建产物（缓存优先）
 *  - 导航请求：网络优先，离线时回退缓存的应用外壳（SPA 离线打开）
 *  - 业务接口（/api、/static）：绝不缓存（避免陈旧数据与隐私泄露）
 */

/* 缓存名称：携带版本号，升级时清除旧缓存 */
const CACHE_NAME = 'storycanvas-shell-v1';

/* 预缓存清单：构建期稳定存在的静态资源 */
const PRECACHE_URLS = [
  './',
  './index.html',
  './manifest.webmanifest',
  './favicon.svg',
  './brand-mark.svg',
  './brand-logo.svg',
  './icons.svg',
  './pwa-192.png',
  './pwa-512.png',
  './apple-touch-icon.png',
];

/* 安装：预缓存应用外壳；等待全部成功，任一失败则跳过安装 */
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting()),
  );
});

/* 激活：清理旧版本缓存，并立即接管页面 */
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/* 请求分发 */
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  /* 仅处理同源 GET 请求 */
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;

  /* 业务接口不缓存：直接走网络 */
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/static/')) return;

  /* 导航请求（HTML 页面）：网络优先，离线回退缓存外壳 */
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('./index.html', copy));
          return response;
        })
        .catch(() => caches.match('./index.html').then((cached) => cached || caches.match('./'))),
    );
    return;
  }

  /* 静态资源（/assets/ 哈希文件、图标等）：缓存优先，未命中回源并缓存 */
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        /* 只缓存成功且可缓存的响应 */
        if (response && response.status === 200 && (response.type === 'basic' || response.type === 'default')) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
        }
        return response;
      });
    }),
  );
});
