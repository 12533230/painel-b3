/* Service worker do Painel B3 — deixa o app abrir offline com o último painel carregado.
   Estratégia: network-first para o HTML (sempre tenta o painel mais novo, cai no cache se
   estiver sem internet); cache-first para ícones/manifest. Dados ao vivo (B3, Yahoo, BCB)
   NUNCA são cacheados — sempre vão à rede. */
const CACHE = 'painel-b3-v1';
const ESTATICOS = ['app/icon-192.png', 'app/icon-512.png', 'app/icon-maskable-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ESTATICOS.map(u => new Request(u, {cache: 'reload'}))))
    .catch(() => null).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;          // dados ao vivo: sempre rede
  const ehPagina = req.mode === 'navigate' || url.pathname.endsWith('.html') || url.pathname.endsWith('/');
  if (ehPagina) {
    e.respondWith(fetch(req).then(r => {
      const copia = r.clone();
      caches.open(CACHE).then(c => c.put(req, copia)).catch(() => {});
      return r;
    }).catch(() => caches.match(req).then(r => r || caches.match('index.html'))));
    return;
  }
  e.respondWith(caches.match(req).then(r => r || fetch(req).then(resp => {
    const copia = resp.clone();
    caches.open(CACHE).then(c => c.put(req, copia)).catch(() => {});
    return resp;
  })));
});
