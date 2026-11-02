import type { Plugin } from 'vite'
import { createHash } from 'node:crypto'

/** The worker can serve only the installed IDE shell and its exact public asset allowlist. */
export function offlineShell(): Plugin {
  let base = '/'
  return {
    name: 'olympiad-offline-shell', apply: 'build',
    configResolved(config) { base = config.base },
    generateBundle(_options, bundle) {
      const files = [`${base}index.html`, ...Object.keys(bundle).filter(name => name !== 'index.html').map(name => `${base}${name}`)]
      const version = createHash('sha256').update(base + files.join('\n')).digest('hex').slice(0, 16)
      const prefix = `olympiad-shell-${createHash('sha256').update(base).digest('hex').slice(0, 12)}-`
      this.emitFile({ type: 'asset', fileName: 'sw.js', source: `
const PREFIX = ${JSON.stringify(prefix)};
const CACHE = PREFIX + ${JSON.stringify(version)};
const BASE = ${JSON.stringify(base)};
const FILES = ${JSON.stringify(files)};
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith(PREFIX) && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.search) return;
  if (event.request.mode === 'navigate' && (url.pathname === BASE || url.pathname === BASE + 'index.html')) {
    event.respondWith(fetch(event.request).catch(() => caches.match(BASE + 'index.html')));
    return;
  }
  if (!FILES.includes(url.pathname)) return;
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
` })
    },
  }
}
