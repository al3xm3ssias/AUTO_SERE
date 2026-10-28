/* Service worker mínimo do Auto SERE.
 * Existe para o Chrome tratar o app como instalável. NÃO faz cache: o
 * sistema depende de dados e execuções ao vivo, e cache velho esconderia
 * o estado real das automações. */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', () => { /* passa direto para a rede */ });
