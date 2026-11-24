/* seguranca.js — a parte do navegador da segurança (carregado ANTES do app.js).
   1. Põe o token CSRF em todo fetch de escrita para o próprio sistema.
   2. Sessão vencida (401): volta para a tela de entrada, em vez de mostrar erros soltos.
   3. Inatividade: sem mexer no sistema por N minutos, pergunta "Estender essa sessão?". Sem nada rodando e sem resposta em 60 s, sai;
      com automação/fila rodando, não sai sozinho (só a pergunta fica até alguém responder).
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
  // Passou do limite: em vez de sair de repente, PERGUNTA "Estender essa sessão?".
  //  - com tarefa em andamento (automação do SERE, fila do WhatsApp): nunca sai sozinho; a pergunta fica até alguém responder;
  //  - sem nada rodando: dá 60 s para responder e, sem resposta, sai (como antes).
  var ESPERA_S = 60;
  var aviso = null;
  function rotulo(nomes) { return nomes.length ? nomes.join(", ") : ""; }
  function consultarSessao() {
    return originalFetch("/web/api/seguranca/sessao", { credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401) { sairParaEntrada("inatividade"); return null; }
        return r.ok ? r.json() : { ocupado: [] };
      })
      .catch(function () { return { ocupado: [] }; });
  }
  function fecharPergunta() {
    if (!aviso) { return; }
    clearInterval(aviso.timer);
    aviso.caixa.remove();
    aviso = null;
    ultimo = Date.now();
  }
  function estender() {
    originalFetch("/web/api/seguranca/estender", { method: "POST", headers: { "X-CSRF-Token": csrf }, credentials: "same-origin" })
      .then(function (r) { if (r.status === 401) { sairParaEntrada("inatividade"); } })
      .catch(function () { /* sem resposta: a próxima consulta decide */ })
      .then(fecharPergunta);
  }
  function perguntar() {
    if (aviso || saindo) { return; }
    var caixa = document.createElement("div");
    caixa.setAttribute("role", "alertdialog");
    caixa.setAttribute("aria-live", "assertive");
    caixa.style.cssText = "position:fixed;inset:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.55)";
    var painel = document.createElement("div");
    painel.style.cssText = "max-width:440px;margin:16px;padding:20px 22px;border-radius:12px;background:var(--surface,#161b26);color:var(--text,#e8ecf4);border:1px solid var(--border,#2a3142);box-shadow:0 12px 40px rgba(0,0,0,.5)";
    var titulo = document.createElement("h3");
    titulo.textContent = "Estender essa sessão?";
    titulo.style.margin = "0 0 8px";
    var texto = document.createElement("p");
    texto.style.cssText = "margin:0 0 14px;line-height:1.45";
    var botoes = document.createElement("div");
    botoes.style.cssText = "display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap";
    var bSair = document.createElement("button");
    bSair.type = "button"; bSair.className = "btn"; bSair.textContent = "Sair agora";
    var bSim = document.createElement("button");
    bSim.type = "button"; bSim.className = "btn btn-primary"; bSim.textContent = "Estender sessão";
    botoes.appendChild(bSair); botoes.appendChild(bSim);
    painel.appendChild(titulo); painel.appendChild(texto); painel.appendChild(botoes);
    caixa.appendChild(painel);
    document.body.appendChild(caixa);
    aviso = { caixa: caixa, fim: null, ocupado: [], timer: null, consultando: false };
    bSim.addEventListener("click", estender);
    bSair.addEventListener("click", function () { sair("manual"); });
    bSim.focus();

    function desenhar() {
      if (!aviso) { return; }
      if (aviso.ocupado.length) {
        aviso.fim = null;
        texto.textContent = "O AUTO SERE está trabalhando (" + rotulo(aviso.ocupado) + "). Sua sessão não vai ser encerrada enquanto isso, "
          + "mas confirme que você ainda está aí.";
      } else {
        if (aviso.fim === null) { aviso.fim = Date.now() + ESPERA_S * 1000; }
        var falta = Math.max(0, Math.ceil((aviso.fim - Date.now()) / 1000));
        texto.textContent = "Você ficou um tempo sem usar o sistema. A sessão será encerrada em " + falta + " s se nada for feito.";
        if (falta <= 0) { sair("inatividade"); }
      }
    }
    function ciclo() {
      if (!aviso || aviso.consultando) { return; }
      aviso.consultando = true;
      consultarSessao().then(function (info) {
        if (!aviso) { return; }
        aviso.consultando = false;
        aviso.ocupado = (info && info.ocupado) || [];
        desenhar();
      });
    }
    var voltas = 0;
    aviso.timer = setInterval(function () { voltas += 1; desenhar(); if (voltas % 5 === 0) { ciclo(); } }, 1000);
    ciclo();
    desenhar();
  }
  setInterval(function () { if (!saindo && !aviso && Date.now() - ultimo > limite) { perguntar(); } }, 15000);
  window.autoSerePerguntarSessao = perguntar;

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
