/* Service worker do Painel B3 — deixa o app abrir offline com o último painel carregado.

   Estratégia:
   · HTML: rede primeiro, com {cache:'no-store'} para NÃO usar o cache HTTP do
     navegador. O GitHub Pages manda Cache-Control: max-age=600 em todo HTML, e o
     APK aponta para o Pages — sem o no-store o app podia abrir com o painel de
     10 minutos atrás mesmo online. Se a rede falhar, cai no cache (é o modo
     offline; a faixa de "dado atrasado" da própria página avisa a idade).
   · Ícones/manifest: responde do cache e atualiza em segundo plano
     (stale-while-revalidate). Antes era cache-first sem nenhuma revalidação, o
     que congelava ícone e manifest para sempre.
   · Dados ao vivo (B3, Yahoo, BCB, raw.githubusercontent) são de outra origem e
     nunca passam por aqui — vão sempre à rede.
*/
const CACHE = 'painel-b3-v2';
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
    e.respondWith(fetch(req, {cache: 'no-store'}).then(r => {
      const copia = r.clone();
      caches.open(CACHE).then(c => c.put(req, copia)).catch(() => {});
      return r;
    }).catch(() => caches.match(req).then(r => r || caches.match('index.html'))));
    return;
  }
  // estáticos: entrega o do cache na hora e busca a versão nova para a próxima
  e.respondWith(caches.match(req).then(cacheado => {
    const rede = fetch(req).then(resp => {
      const copia = resp.clone();
      caches.open(CACHE).then(c => c.put(req, copia)).catch(() => {});
      return resp;
    }).catch(() => null);   // offline com item em cache: a falha não pode virar erro solto
    return cacheado || rede.then(r => r || Response.error());
  }));
});
