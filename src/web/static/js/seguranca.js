/* seguranca.js — a parte do navegador da segurança (carregado ANTES do app.js).
   1. Põe o token CSRF em todo fetch de escrita para o próprio sistema.
   2. Sessão vencida (401): volta para a tela de entrada, em vez de mostrar erros soltos.
   3. Bloqueio por inatividade: sem mexer no sistema por N minutos, sai sozinho (mesmo com a tela fazendo consultas em segundo plano).
   4. Topo: nome e perfil de quem entrou e o botão Sair; esconde o que o perfil não pode usar (o servidor confere de qualquer jeito). */
(function () {
  "use strict";

  var metaCsrf = document.querySelector('meta[name="csrf-token"]');
  var metaIdle = document.querySelector('meta[name="auto-sere-inatividade"]');
  var csrf = metaCsrf ? metaCsrf.getAttribute("content") : "";
  var saindo = false;

  if (!csrf) { return; }            // páginas sem login (testes antigos, telas de entrada): nada a fazer

  var originalFetch = window.fetch.bind(window);
  window.fetch = function (entrada, opcoes) {
    opcoes = opcoes || {};
    var metodo = String(opcoes.method || (entrada && entrada.method) || "GET").toUpperCase();
    var alvo = typeof entrada === "string" ? entrada : (entrada && entrada.url) || "";
    var mesmaOrigem = alvo.charAt(0) === "/" && alvo.charAt(1) !== "/" || alvo.indexOf(window.location.origin + "/") === 0;
    if (mesmaOrigem && ["GET", "HEAD", "OPTIONS"].indexOf(metodo) === -1) {
      var cab = new Headers(opcoes.headers || (typeof entrada !== "string" && entrada && entrada.headers) || {});
      if (!cab.has("X-CSRF-Token")) { cab.set("X-CSRF-Token", csrf); }
      opcoes.headers = cab;
    }
    return originalFetch(entrada, opcoes).then(function (resp) {
      if (resp.status === 401 && mesmaOrigem && !saindo) {
        resp.clone().json().then(function (d) {
          if (d && d.autenticacao) { sairParaEntrada("sessao"); }
        }).catch(function () { /* resposta sem JSON */ });
      }
      return resp;
    });
  };

  function sairParaEntrada(motivo) {
    if (saindo) { return; }
    saindo = true;
    window.location.assign("/web/entrar" + (motivo === "inatividade" ? "?motivo=inatividade" : ""));
  }

  function sair(motivo) {
    saindo = true;
    originalFetch("/web/api/seguranca/sair", { method: "POST", headers: { "X-CSRF-Token": csrf }, credentials: "same-origin" })
      .catch(function () { /* mesmo sem resposta, sai da tela */ })
      .then(function () { window.location.assign("/web/entrar" + (motivo === "inatividade" ? "?motivo=inatividade" : "")); });
  }
  window.autoSereSair = sair;

  // ---- inatividade: só gestos reais do usuário contam (a tela consulta o servidor sozinha de tempos em tempos)
  var limite = (parseInt(metaIdle && metaIdle.getAttribute("content"), 10) || 1200) * 1000;
  var ultimo = Date.now();
  var ultimoMove = 0;
  ["mousedown", "keydown", "touchstart", "wheel", "scroll"].forEach(function (nome) {
    window.addEventListener(nome, function () { ultimo = Date.now(); }, { passive: true, capture: true });
  });
  window.addEventListener("mousemove", function () {
    var agora = Date.now();
    if (agora - ultimoMove > 5000) { ultimoMove = agora; ultimo = agora; }
  }, { passive: true });
  setInterval(function () { if (!saindo && Date.now() - ultimo > limite) { sair("inatividade"); } }, 15000);

  // ---- topo: quem entrou
  document.addEventListener("DOMContentLoaded", function () {
    var perfil = document.body.getAttribute("data-perfil") || "";
    if (perfil) { document.body.classList.add("perfil-" + perfil); }
    var caixa = document.getElementById("topbar-user");
    if (!caixa) { return; }
    var nome = document.body.getAttribute("data-usuario-nome") || "";
    var rotulo = document.body.getAttribute("data-perfil-rotulo") || "";
    if (nome) {
      caixa.classList.add("logado");
      caixa.title = "Minha conta: " + nome + " (" + rotulo + ")";
      var texto = document.createElement("span");
      texto.className = "topbar-user-nome";
      texto.textContent = nome;
      var pequeno = document.createElement("small");
      pequeno.textContent = rotulo;
      texto.appendChild(pequeno);
      caixa.appendChild(texto);
    }
    var botao = document.getElementById("btn-sair");
    if (botao) { botao.addEventListener("click", function () { sair("manual"); }); }
  });
})();
