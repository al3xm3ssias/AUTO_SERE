/* usuarios.js — painéis de Configurações: "Minha conta" (todos) e "Usuários e segurança" (só administrador).
   Todo texto vindo do servidor entra por textContent (nunca innerHTML): nome de usuário é dado digitado por alguém. */
(function () {
  "use strict";

  function el(tag, atributos, filhos) {
    var n = document.createElement(tag);
    Object.keys(atributos || {}).forEach(function (k) {
      if (k === "texto") { n.textContent = atributos[k]; } else if (k === "classe") { n.className = atributos[k]; } else { n.setAttribute(k, atributos[k]); }
    });
    (filhos || []).forEach(function (f) { n.appendChild(typeof f === "string" ? document.createTextNode(f) : f); });
    return n;
  }

  function chamar(metodo, caminho, corpo) {
    return fetch("/web/api/seguranca" + caminho, {
      method: metodo, headers: { "Content-Type": "application/json" }, body: corpo === undefined ? undefined : JSON.stringify(corpo), credentials: "same-origin"
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) { var e = new Error(d.erro || d.mensagem || "Erro " + r.status); e.problemas = d.problemas || []; throw e; }
        return d;
      });
    });
  }

  function dataBr(iso) { if (!iso) { return "—"; } var d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString("pt-BR"); }

  function avisar(caixa, texto, ruim) {
    caixa.textContent = texto || "";
    caixa.style.color = ruim ? "var(--rose)" : "var(--lime)";
  }

  // ---------------- Minha conta
  function montarMinhaConta(raiz) {
    var nome = document.body.getAttribute("data-usuario-nome") || "";
    var rotulo = document.body.getAttribute("data-perfil-rotulo") || "";
    var login = document.body.getAttribute("data-usuario-login") || "";
    raiz.textContent = "";
    raiz.appendChild(el("h4", { texto: "Minha conta", style: "margin-bottom:10px;font-size:.9rem;" }));
    raiz.appendChild(el("p", { style: "color:var(--txt3);font-size:.82rem;margin-bottom:14px;max-width:560px;",
      texto: "Você entrou como " + nome + " (usuário " + login + ", perfil " + rotulo + "). A senha do AUTO SERE é só sua e não tem relação com a do SERE." }));
    var trocar = el("a", { classe: "btn-primary", href: "/web/trocar-senha", texto: "Trocar a minha senha", style: "text-decoration:none;display:inline-block;" });
    var sair = el("button", { classe: "usr-btn", type: "button", texto: "Sair do sistema", style: "margin-left:10px;" });
    sair.addEventListener("click", function () { window.autoSereSair && window.autoSereSair("manual"); });
    raiz.appendChild(el("div", {}, [trocar, sair]));
  }

  // ---------------- Usuários (admin)
  function montarUsuarios(raiz) {
    raiz.textContent = "";
    raiz.appendChild(el("h4", { texto: "Usuários e segurança", style: "margin-bottom:6px;font-size:.9rem;" }));
    raiz.appendChild(el("p", { style: "color:var(--txt3);font-size:.82rem;margin-bottom:8px;max-width:640px;",
      texto: "Administrador: tudo. Operador: executa as automações e edita registros. Consulta: só vê. Pedagoga: só consulta Turmas, Alunos e Encaminhamentos SUS e roda as coletas Turmas e Alunos. As senhas são guardadas só como hash (Argon2id); ninguém, nem o sistema, consegue ler uma senha." }));
    var aviso = el("p", { style: "font-size:.8rem;min-height:1.2em;", role: "status" });
    var segredo = el("div", {});
    var tabelaBox = el("div", { classe: "usr-tabela-box" });
    var auditoriaBox = el("div", {});

    var selPerfil = el("select", { id: "usr-novo-perfil" }, [
      el("option", { value: "operador", texto: "Operador" }), el("option", { value: "consulta", texto: "Consulta" }), el("option", { value: "admin", texto: "Administrador" }), el("option", { value: "pedagoga", texto: "Pedagoga" })]);
    var inUsuario = el("input", { type: "text", id: "usr-novo-usuario", autocomplete: "off", autocapitalize: "none" });
    var inNome = el("input", { type: "text", id: "usr-novo-nome", autocomplete: "off", maxlength: "80" });
    var btnCriar = el("button", { classe: "btn-primary", type: "button", texto: "Criar usuário" });
    var form = el("div", { classe: "usr-linha-form" }, [
      el("div", { classe: "field" }, [el("label", { texto: "Usuário", for: "usr-novo-usuario" }), inUsuario]),
      el("div", { classe: "field" }, [el("label", { texto: "Nome", for: "usr-novo-nome" }), inNome]),
      el("div", { classe: "field" }, [el("label", { texto: "Perfil", for: "usr-novo-perfil" }), selPerfil]),
      el("div", { classe: "field" }, [btnCriar])]);
    raiz.appendChild(el("div", { classe: "sec-hdr", style: "margin-top:12px;" }, [el("span", { classe: "sec-ttl", texto: "Novo usuário" })]));
    raiz.appendChild(form);
    raiz.appendChild(el("p", { style: "color:var(--txt3);font-size:.74rem;", texto: "O sistema gera uma senha temporária; a pessoa é obrigada a trocá-la no primeiro acesso." }));
    raiz.appendChild(aviso);
    raiz.appendChild(segredo);
    raiz.appendChild(el("div", { classe: "sec-hdr", style: "margin-top:14px;" }, [el("span", { classe: "sec-ttl", texto: "Usuários cadastrados" })]));
    raiz.appendChild(tabelaBox);
    raiz.appendChild(el("div", { classe: "sec-hdr", style: "margin-top:14px;" }, [el("span", { classe: "sec-ttl", texto: "Registro de segurança (auditoria)" })]));
    raiz.appendChild(auditoriaBox);

    function mostrarSegredo(titulo, senha) {
      segredo.textContent = "";
      if (!senha) { return; }
      segredo.appendChild(el("p", { style: "font-size:.8rem;", texto: titulo + " Anote agora: ela não será mostrada de novo." }));
      segredo.appendChild(el("div", { classe: "usr-segredo", texto: senha }));
    }

    function acao(promessa, ok) {
      avisar(aviso, "");
      promessa.then(function (d) { avisar(aviso, ok || "Feito."); if (d && d.senha_temporaria) { mostrarSegredo("Senha temporária:", d.senha_temporaria); } carregar(); })
        .catch(function (e) { avisar(aviso, e.message + (e.problemas && e.problemas.length ? " " + e.problemas.join(" ") : ""), true); });
    }

    function carregar() {
      chamar("GET", "/usuarios").then(function (d) {
        var cab = el("tr", {}, ["Usuário", "Perfil", "Situação", "Último acesso", "Ações"].map(function (t) { return el("th", { texto: t }); }));
        var linhas = d.usuarios.map(function (u) {
          var situacao = [];
          situacao.push(el("span", { classe: "usr-selo" + (u.ativo ? "" : " ruim"), texto: u.ativo ? "Ativo" : "Desativado" }));
          if (u.bloqueado) { situacao.push(" ", el("span", { classe: "usr-selo ruim", texto: "Bloqueado" })); }
          if (u.trocar_senha) { situacao.push(" ", el("span", { classe: "usr-selo", texto: "Senha temporária" })); }
          var perfil = el("select", { "aria-label": "Perfil de " + u.usuario }, d.perfis.map(function (p) {
            var o = el("option", { value: p.id, texto: p.rotulo }); if (p.id === u.perfil) { o.selected = true; } return o; }));
          perfil.addEventListener("change", function () { acao(chamar("PATCH", "/usuarios/" + encodeURIComponent(u.id), { perfil: perfil.value }), "Perfil alterado; a pessoa precisa entrar de novo."); });
          var botoes = [];
          function botao(rotulo, icone, fn, perigo) {
            var b = el("button", { type: "button", classe: "usr-ico" + (perigo ? " usr-perigo" : ""), "aria-label": rotulo + " — " + u.usuario, "data-dica": rotulo });
            b.innerHTML = (typeof ICONS !== "undefined" && ICONS[icone]) ? ICONS[icone]() : "•";   // só o ícone dentro do botão; o nome vem da dica (data-dica)
            b.addEventListener("click", fn); botoes.push(b);
          }
          botao("Redefinir senha", "key", function () { if (confirm("Gerar uma nova senha temporária para " + u.usuario + "? As sessões dele serão encerradas.")) { acao(chamar("POST", "/usuarios/" + encodeURIComponent(u.id) + "/redefinir-senha", {}), "Senha redefinida."); } });
          if (u.bloqueado) { botao("Desbloquear", "unlock", function () { acao(chamar("POST", "/usuarios/" + encodeURIComponent(u.id) + "/desbloquear", {}), "Desbloqueado."); }); }
          botao(u.ativo ? "Desativar" : "Ativar", u.ativo ? "ban" : "circleCheck", function () { acao(chamar("PATCH", "/usuarios/" + encodeURIComponent(u.id), { ativo: !u.ativo }), u.ativo ? "Desativado." : "Ativado."); });
          botao("Apagar", "trash", function () { if (confirm("Apagar o usuário " + u.usuario + "? Isso não pode ser desfeito.")) { acao(chamar("DELETE", "/usuarios/" + encodeURIComponent(u.id)), "Usuário apagado."); } }, true);
          var identidade = [el("div", { classe: "usr-id", texto: u.usuario })];
          if (u.nome && u.nome !== u.usuario) { identidade.push(el("div", { classe: "usr-nome", texto: u.nome, title: u.nome })); }
          return el("tr", {}, [el("td", {}, identidade), el("td", {}, [perfil]), el("td", {}, [el("div", { classe: "usr-situacao" }, situacao)]),
            el("td", { texto: dataBr(u.ultimo_login) }), el("td", {}, [el("div", { classe: "usr-acoes" }, botoes)])]);
        });
        tabelaBox.textContent = "";
        tabelaBox.appendChild(el("table", { classe: "usr-tabela" }, [el("thead", {}, [cab]), el("tbody", {}, linhas)]));
      }).catch(function (e) { avisar(aviso, e.message, true); });
      chamar("GET", "/auditoria?limite=60").then(function (d) {
        auditoriaBox.textContent = "";
        var c = d.corrente || {};
        auditoriaBox.appendChild(el("p", { style: "font-size:.76rem;margin-bottom:6px;color:" + (c.integra ? "var(--lime)" : "var(--rose)"),
          texto: c.integra ? "Registro íntegro (" + c.linhas + " eventos, sem quebras na corrente)." : "ATENÇÃO: a corrente do registro está quebrada na linha " + c.primeira_quebra + " — o arquivo foi alterado." }));
        var caixa = el("div", { classe: "usr-audit" });
        var corpo = el("tbody", {});
        var diaAtual = "";
        d.eventos.forEach(function (e) {
          var dt = e.ts ? new Date(e.ts) : null, valida = dt && !isNaN(dt);
          var dia = valida ? dt.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" }) : "Sem data";
          if (dia !== diaAtual) {
            diaAtual = dia;
            corpo.appendChild(el("tr", { classe: "usr-audit-dia" }, [el("td", { colspan: "5", texto: dia })]));
          }
          var ruim = /negad|recusad|bloque|falh|erro|limite|tentativa/i.test(e.evento || "");
          corpo.appendChild(el("tr", {}, [
            el("td", { classe: "usr-audit-hora", texto: valida ? dt.toLocaleTimeString("pt-BR") : "—" }),
            el("td", {}, [el("span", { classe: "usr-selo" + (ruim ? " ruim" : ""), texto: e.descricao || e.evento })]),
            el("td", { texto: e.usuario || "—" }),
            el("td", { classe: "usr-audit-ip", texto: e.ip || "—" }),
            el("td", { classe: "usr-audit-det", texto: e.detalhe || "" })]));
        });
        caixa.appendChild(el("table", { classe: "usr-audit-tabela" }, [
          el("thead", {}, [el("tr", {}, ["Hora", "Evento", "Usuário", "IP", "Detalhe"].map(function (h) { return el("th", { texto: h }); }))]), corpo]));
        auditoriaBox.appendChild(caixa);
      }).catch(function () { /* sem permissão ou sem registro ainda */ });
    }

    btnCriar.addEventListener("click", function () {
      acao(chamar("POST", "/usuarios", { usuario: inUsuario.value, nome: inNome.value, perfil: selPerfil.value }), "Usuário criado.");
      inUsuario.value = ""; inNome.value = "";
    });
    carregar();
  }

  // As entradas do painel precisam existir ANTES do clique do app.js (que lê DETALHE_CONFIG). O app.js é carregado antes deste arquivo.
  if (typeof DETALHE_CONFIG !== "undefined") {
    DETALHE_CONFIG.minha_conta = '<div id="cfg-minha-conta"></div>';
    DETALHE_CONFIG.usuarios = '<div id="cfg-usuarios"></div>';
  }
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('.config-row[data-config="minha_conta"], .config-row[data-config="usuarios"]').forEach(function (linha) {
      linha.addEventListener("click", function () {
        var raiz = document.getElementById(linha.dataset.config === "usuarios" ? "cfg-usuarios" : "cfg-minha-conta");
        if (!raiz) { return; }
        if (linha.dataset.config === "usuarios") { montarUsuarios(raiz); } else { montarMinhaConta(raiz); }
      });
    });
  });
})();
