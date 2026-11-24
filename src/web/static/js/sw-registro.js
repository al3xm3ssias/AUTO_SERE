/* Registra o service worker (necessário para o Chrome oferecer "Instalar"). Falha em silêncio.
   Fica em arquivo próprio porque a política de segurança do sistema não aceita script inline. */
(function () {
  var self = document.currentScript;
  if ('serviceWorker' in navigator && self) {
    navigator.serviceWorker.register(self.getAttribute('data-sw'), { scope: '/' }).catch(function () {});
  }
})();
