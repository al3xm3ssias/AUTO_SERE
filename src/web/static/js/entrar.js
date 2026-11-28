/* entrar.js — telas de entrada: entrar, criar o administrador (instalação) e trocar a senha.
   Sem script inline (a política de segurança do sistema só aceita scripts deste arquivo e dos demais em /web/static/js). */
(function () {
  "use strict";

  try { document.documentElement.setAttribute("data-theme", localStorage.getItem("auto_sere_tema") || "escuro"); } catch (e) { /* sem localStorage */ }

  var form = document.getElementById("auth-form");
  if (!form) { return; }
  var modo = form.getAttribute("data-modo");
  var url = form.getAttribute("data-url");
  var erro = document.getElementById("auth-erro");
  var botao = document.getElementById("auth-enviar");
  var meta = document.querySelector('meta[name="csrf-token"]');

  function mostrarErro(mensagem, problemas) {
    erro.textContent = "";
    var p = document.createElement("span");
    p.textContent = mensagem;
    erro.appendChild(p);
    if (problemas && problemas.length) {
      var ul = document.createElement("ul");
      problemas.forEach(function (t) { var li = document.createElement("li"); li.textContent = t; ul.appendChild(li); });
      erro.appendChild(ul);
    }
    erro.hidden = false;
  }

  function valor(id) { var el = document.getElementById(id); return el ? el.value : ""; }

  // mostrar/esconder senha
  document.querySelectorAll(".auth-olho").forEach(function (b) {
    b.addEventListener("click", function () {
      var campo = document.getElementById(b.getAttribute("data-alvo"));
      var visivel = campo.type === "text";
      campo.type = visivel ? "password" : "text";
      b.textContent = visivel ? "Mostrar" : "Esconder";
    });
  });

  // lista de regras ao vivo (o servidor é quem decide de verdade; isto só orienta)
  var senhaEl = document.getElementById("auth-senha");
  var regras = document.getElementById("auth-regras");
  function atualizarRegras() {
    if (!regras || !senhaEl) { return; }
    var s = senhaEl.value;
    var classes = [/[a-zà-ú]/.test(s), /[A-ZÀ-Ú]/.test(s), /[0-9]/.test(s), /[^A-Za-zÀ-ú0-9]/.test(s)].filter(Boolean).length;
    var u = valor("auth-usuario").toLowerCase();
    var estado = {
      "tamanho": s.length >= 8,
      "mistura": s.length >= 16 || classes >= 3,
      "sem-usuario": !(u.length >= 3 && s.toLowerCase().indexOf(u) !== -1)
    };
    regras.querySelectorAll("li").forEach(function (li) { li.classList.toggle("ok", !!estado[li.getAttribute("data-regra")] && s.length > 0); });
  }
  if (senhaEl) { senhaEl.addEventListener("input", atualizarRegras); }
  var usuarioEl = document.getElementById("auth-usuario");
  if (usuarioEl && modo !== "entrar") { usuarioEl.addEventListener("input", atualizarRegras); }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    erro.hidden = true;
    var corpo;
    if (modo === "entrar") {
      if (!valor("auth-usuario").trim() || !valor("auth-senha")) { mostrarErro("Informe o usuário e a senha."); return; }
      corpo = { usuario: valor("auth-usuario"), senha: valor("auth-senha"), proximo: valor("auth-proximo") };
    } else if (modo === "instalacao") {
      if (valor("auth-senha") !== valor("auth-confirmacao")) { mostrarErro("A confirmação não é igual à senha."); return; }
      corpo = { usuario: valor("auth-usuario"), nome: valor("auth-nome"), senha: valor("auth-senha"), confirmacao: valor("auth-confirmacao") };
    } else {
      if (valor("auth-senha") !== valor("auth-confirmacao")) { mostrarErro("A confirmação não é igual à senha nova."); return; }
      corpo = { atual: valor("auth-atual"), nova: valor("auth-senha"), confirmacao: valor("auth-confirmacao") };
    }
    var cabecalhos = { "Content-Type": "application/json" };
    if (meta) { cabecalhos["X-CSRF-Token"] = meta.getAttribute("content"); }
    botao.disabled = true;
    var rotulo = botao.textContent;
    botao.textContent = "Aguarde…";
    fetch(url, { method: "POST", headers: cabecalhos, body: JSON.stringify(corpo), credentials: "same-origin" })
      .then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (res.ok && res.d.ok) { window.location.assign(res.d.proximo || "/web"); return; }
        mostrarErro(res.d.erro || res.d.mensagem || "Não foi possível concluir. Tente de novo.", res.d.problemas);
      })
      .catch(function () { mostrarErro("Sem resposta do servidor. O AUTO SERE está aberto? Tente de novo."); })
      .then(function () { botao.disabled = false; botao.textContent = rotulo; });
  });
})();
