/* ============================================================
   AUTO SERE — ajuda.js
   Ajuda contextual (tecla F1) e Central de ajuda.

   • F1 (ou o botão ? do alto) abre um painel com a ajuda da tela em que você está e, quando há, da aba, do painel
     de Configurações, da automação ou da janela aberta por cima. Aperte F1 ou Esc para fechar.
   • Os textos vêm do servidor (GET /web/api/ajuda/<tipo>/<chave>), montados por src/comum/ajuda.py.
   • "Mostrar na tela" destaca o botão ou campo real de cada item da ajuda.
   Tudo numa IIFE; nada é exposto além de window.abrirAjuda / window.fecharAjuda.
   ============================================================ */
(function () {
  "use strict";

  const API = "/web/api/ajuda";
  const cache = {};                      // "tipo/chave" -> ajuda já baixada
  let geralCache = null;
  let painel = null;                     // elementos do painel (criados na primeira abertura)
  let aberto = false;
  let niveis = [];                       // [{tipo, chave, rotulo}] do mais específico para o mais geral
  let nivelAtivo = 0;
  let pilha = [];                        // histórico de "Veja também" dentro do painel
  let focoAnterior = null;
  let ultimaConfig = null;               // último painel de Configurações aberto pelo usuário

  const ROTULO_TIPO = { tela: "Tela", aba: "Aba", configuracao: "Painel", modal: "Janela", automacao: "Automação" };

  /* ---------- utilitários ---------- */

  const $ = (id) => document.getElementById(id);

  function esc(t) {
    return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /** **negrito**, `código` e quebras de linha; todo o resto é texto puro (escapado). */
  function md(t) {
    return esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\n/g, "<br>");
  }

  function icone(nome) {
    return typeof icon === "function" ? icon(nome || "help") : "";
  }

  async function buscar(tipo, chave) {
    const k = `${tipo}/${chave}`;
    if (cache[k]) return cache[k];
    try {
      const r = await fetch(`${API}/${encodeURIComponent(tipo)}/${encodeURIComponent(chave)}`);
      if (!r.ok) throw new Error("sem ajuda");
      cache[k] = await r.json();
    } catch (e) {
      return null;
    }
    return cache[k];
  }

  async function buscarGeral() {
    if (geralCache) return geralCache;
    try {
      const r = await fetch(`${API}/geral`);
      if (r.ok) geralCache = await r.json();
    } catch (e) { /* segue sem a seção "Em todas as telas" */ }
    return geralCache;
  }

  /* ---------- onde o usuário está ---------- */

  function viewAtiva() {
    const sec = document.querySelector(".section.active");
    return sec ? sec.id.replace(/^sec-/, "") : "painel";
  }

  /** Janela (modal) aberta por cima da tela, reconhecida pelo título; null se não há. */
  function detectarModal() {
    const fundos = document.querySelectorAll(".modal-overlay");
    if (!fundos.length) return null;
    const topo = fundos[fundos.length - 1];
    if (topo.querySelector("#mdl-pergunta-valor")) return "pergunta-automacao";
    const titulo = (topo.querySelector("h3")?.textContent || "").trim();
    const mapa = [
      ["Confirmar execução", "confirmar-execucao"],
      ["Credenciais do SERE", "credenciais-sere"],
      ["Dados da escola", "dados-escola"],
      ["Nova planilha", "planilha-formulario"],
      ["Editar planilha", "planilha-formulario"],
      ["Criar planilha a partir", "planilha-modelo"],
      ["Mensagem para o responsável", "mensagem-responsavel"],
    ];
    const achado = mapa.find(([inicio]) => titulo.startsWith(inicio));
    return achado ? achado[1] : null;
  }

  function execucaoAberta() {
    const caixa = $("automacoes-execucao");
    return !!caixa && getComputedStyle(caixa).display !== "none"
      && typeof automacaoAtual !== "undefined" && !!automacaoAtual;
  }

  /** Lista de ajudas aplicáveis agora, da mais específica (janela, aba, painel, automação) para a mais geral (a tela). */
  function contextos() {
    const lista = [];
    const modal = detectarModal();
    if (modal) lista.push({ tipo: "modal", chave: modal });

    const view = viewAtiva();
    if (view === "automacoes" && execucaoAberta()) {
      lista.push({ tipo: "automacao", chave: automacaoAtual });
    } else if (view === "documentos") {
      const aba = document.querySelector(".doc-tab.active")?.dataset.doctab;
      if (aba) lista.push({ tipo: "aba", chave: `documentos-${aba}` });
    } else if (view === "configuracoes") {
      const aberto = $("config-detalhe")?.querySelector("h4, #cfg-escola-form");
      if (aberto && ultimaConfig) lista.push({ tipo: "configuracao", chave: ultimaConfig });
    } else if (view === "prematricula") {
      const exec = $("pm-exec");
      if (exec && exec.style.display !== "none") lista.push({ tipo: "aba", chave: "prematricula-executar" });
    }
    lista.push({ tipo: "tela", chave: view });
    return lista;
  }

  /* ---------- desenho do painel ---------- */

  function montarPainel() {
    if (painel) return painel;
    const fundo = document.createElement("div");
    fundo.id = "ajuda-fundo";
    fundo.className = "ajuda-fundo";
    fundo.hidden = true;
    fundo.innerHTML = `
      <aside class="ajuda-painel" id="ajuda-painel" role="dialog" aria-modal="true" aria-labelledby="ajuda-titulo">
        <header class="ajuda-topo">
          <button class="ajuda-voltar" id="ajuda-voltar" type="button" hidden aria-label="Voltar">${icone("arrowLeft")}</button>
          <div class="ajuda-topo-ic" id="ajuda-icone"></div>
          <div class="ajuda-topo-txt">
            <small>Ajuda · F1</small>
            <h2 id="ajuda-titulo">Ajuda</h2>
          </div>
          <button class="ajuda-btn" id="ajuda-imprimir" type="button" title="Imprimir esta ajuda">${icone("download")}</button>
          <button class="ajuda-btn" id="ajuda-fechar" type="button" aria-label="Fechar ajuda (Esc)" title="Fechar (Esc)">✕</button>
        </header>
        <nav class="ajuda-niveis" id="ajuda-niveis" hidden></nav>
        <div class="ajuda-corpo" id="ajuda-corpo"></div>
        <footer class="ajuda-rodape">
          <button class="btn-sm" id="ajuda-central" type="button">Central de ajuda</button>
          <span>F1 ou Esc para fechar</span>
        </footer>
      </aside>`;
    document.body.appendChild(fundo);
    painel = {
      fundo,
      icone: $("ajuda-icone"), titulo: $("ajuda-titulo"), niveis: $("ajuda-niveis"), corpo: $("ajuda-corpo"),
      voltar: $("ajuda-voltar"),
    };
    fundo.addEventListener("mousedown", (e) => { if (e.target === fundo) fechar(); });
    $("ajuda-fechar").addEventListener("click", fechar);
    $("ajuda-imprimir").addEventListener("click", () => window.print());
    $("ajuda-central").addEventListener("click", () => { fechar(); irParaView("ajuda"); });
    painel.voltar.addEventListener("click", () => {
      pilha.pop();
      const anterior = pilha[pilha.length - 1];
      if (anterior) mostrar(anterior, false); else desenharNivel();
    });
    return painel;
  }

  const SECAO_ID = (i) => `ajuda-sec-${i}`;

  function htmlElemento(el) {
    const mostrar = el.sel ? `<button class="btn-sm aj-mostrar" type="button" data-sel="${esc(el.sel)}">Mostrar na tela</button>` : "";
    return `<div class="aj-el"><div class="aj-el-topo"><strong>${esc(el.nome)}</strong>${mostrar}</div>
      <div class="aj-el-txt">${md(el.texto)}</div></div>`;
  }

  function htmlSecao(s, i) {
    let corpo = "";
    if (s.tipo === "texto") corpo = s.itens.map((t) => `<p>${md(t)}</p>`).join("");
    else if (s.tipo === "passos") corpo = `<ol class="aj-passos">${s.itens.map((t) => `<li>${md(t)}</li>`).join("")}</ol>`;
    else if (s.tipo === "lista") corpo = `<ul class="aj-lista">${s.itens.map((t) => `<li>${md(t)}</li>`).join("")}</ul>`;
    else if (s.tipo === "elementos") corpo = s.itens.map(htmlElemento).join("");
    else if (s.tipo === "links") {
      corpo = `<div class="aj-links">${s.itens.map((l) =>
        `<button class="btn-sm aj-link" type="button" data-tipo="${esc(l.tipo)}" data-chave="${esc(l.chave)}">${esc(l.rotulo)}</button>`).join("")}</div>`;
    }
    return `<section class="aj-sec aj-sec-${esc(s.tipo)}" id="${SECAO_ID(i)}"><h3>${esc(s.titulo)}</h3>${corpo}</section>`;
  }

  /** Pode abrir a tela de verdade? (tela, automação e painel de Configurações têm destino no menu.) */
  function podeIr(a) {
    return ["tela", "automacao", "configuracao"].includes(a.tipo);
  }

  async function mostrar(a, empilhar) {
    const p = montarPainel();
    if (empilhar) pilha.push(a);
    p.voltar.hidden = pilha.length < 2;
    p.titulo.textContent = a.titulo;
    p.icone.innerHTML = icone(a.icone);

    const nav = a.secoes.length > 2
      ? `<div class="aj-indice" aria-label="Seções">${a.secoes.map((s, i) =>
          `<button type="button" class="aj-chip" data-alvo="${SECAO_ID(i)}">${esc(s.titulo)}</button>`).join("")}</div>` : "";
    const ir = podeIr(a) && !(a.tipo === "tela" && a.chave === viewAtiva() && !execucaoAberta() && !detectarModal())
      ? `<button class="btn-sm aj-ir" type="button" data-tipo="${esc(a.tipo)}" data-chave="${esc(a.chave)}">Abrir esta tela</button>` : "";

    const geral = await buscarGeral();
    const geralHtml = geral
      ? `<details class="aj-geral"><summary>${esc(geral.titulo)}</summary><p>${md(geral.resumo)}</p>${
          geral.secoes.map(htmlSecao).join("")}</details>` : "";

    p.corpo.innerHTML = `<p class="aj-resumo">${md(a.resumo)}</p>${ir}${nav}${a.secoes.map(htmlSecao).join("")}${geralHtml}`;
    p.corpo.scrollTop = 0;
    marcarVisiveis();
  }

  /** Desativa "Mostrar na tela" dos elementos que não estão visíveis agora. */
  function marcarVisiveis() {
    painel.corpo.querySelectorAll(".aj-mostrar").forEach((b) => {
      let el = null;
      try { el = document.querySelector(b.dataset.sel); } catch (e) { /* seletor inválido */ }
      const visivel = !!el && el.getClientRects().length > 0;
      b.disabled = !visivel;
      b.title = visivel ? "Destaca este item na tela" : "Este item não está visível agora (abra a aba, o painel ou a janela certa)";
    });
  }

  function destacar(sel) {
    let el = null;
    try { el = document.querySelector(sel); } catch (e) { return; }
    if (!el) return;
    if (window.innerWidth <= 900) fechar();
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("aj-destaque");
    setTimeout(() => el.classList.remove("aj-destaque"), 3200);
  }

  async function desenharNivel() {
    const p = montarPainel();
    const n = niveis[nivelAtivo];
    p.niveis.innerHTML = niveis.length > 1
      ? niveis.map((x, i) => `<button type="button" class="aj-nivel${i === nivelAtivo ? " ativo" : ""}" data-i="${i}">
          <small>${ROTULO_TIPO[x.tipo]}</small>${esc(x.titulo)}</button>`).join("")
      : "";
    p.niveis.hidden = niveis.length < 2;
    pilha = [];
    await mostrar(n.dados, true);
  }

  /* ---------- abrir e fechar ---------- */

  async function abrir(listaForcada) {
    const lista = listaForcada || contextos();
    focoAnterior = document.activeElement;
    const p = montarPainel();
    p.fundo.hidden = false;
    document.body.classList.add("ajuda-aberta");
    aberto = true;
    p.corpo.innerHTML = '<p class="aj-carregando">Carregando a ajuda…</p>';
    $("ajuda-fechar").focus();

    const baixadas = await Promise.all(lista.map((c) => buscar(c.tipo, c.chave)));
    niveis = lista.map((c, i) => ({ ...c, dados: baixadas[i], titulo: baixadas[i]?.titulo || c.chave }))
      .filter((n) => n.dados);
    if (!niveis.length) {
      p.titulo.textContent = "Ajuda";
      p.corpo.innerHTML = '<p class="aj-resumo">Ainda não há ajuda escrita para esta tela. Abra a Central de ajuda para ver as demais.</p>';
      return;
    }
    nivelAtivo = 0;
    await desenharNivel();
  }

  function fechar() {
    if (!aberto) return;
    aberto = false;
    painel.fundo.hidden = true;
    document.body.classList.remove("ajuda-aberta");
    if (focoAnterior && document.contains(focoAnterior)) focoAnterior.focus();
  }

  function alternar() { if (aberto) fechar(); else abrir(); }

  /** Abre a ajuda de um item específico (usado pela Central de ajuda). */
  async function abrirItem(tipo, chave) {
    await abrir([{ tipo, chave }]);
  }

  function irParaView(view) {
    document.querySelector(`.nav-item[data-view="${view}"]:not([data-auto])`)?.click();
  }

  function irPara(tipo, chave) {
    fechar();
    if (tipo === "tela") irParaView(chave);
    else if (tipo === "automacao") document.querySelector(`.nav-subitem[data-auto="${chave}"]`)?.click();
    else if (tipo === "configuracao") {
      irParaView("configuracoes");
      setTimeout(() => document.querySelector(`.config-row[data-config="${chave}"]`)?.click(), 150);
    }
  }

  /* ---------- eventos ---------- */

  function ligar() {
    // F1 em captura, antes de qualquer outro tratamento (inclusive o do navegador, que abre a própria ajuda).
    document.addEventListener("keydown", (e) => {
      if (e.key === "F1" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) {
        e.preventDefault();
        e.stopImmediatePropagation();
        alternar();
      } else if (e.key === "Escape" && aberto) {
        e.preventDefault();
        e.stopImmediatePropagation();     // fecha só a ajuda; a janela embaixo (se houver) continua aberta
        fechar();
      }
    }, true);
    window.addEventListener("help", (e) => e.preventDefault());

    $("btn-ajuda-f1")?.addEventListener("click", alternar);

    // Guarda o último painel de Configurações aberto, para a ajuda saber de qual se trata.
    document.addEventListener("click", (e) => {
      const linha = e.target.closest?.(".config-row[data-config]");
      if (linha) ultimaConfig = linha.dataset.config;
    }, true);

    document.addEventListener("click", (e) => {
      if (!painel || painel.fundo.hidden) return;
      const alvo = e.target;
      const mostrarBtn = alvo.closest(".aj-mostrar");
      if (mostrarBtn) { if (!mostrarBtn.disabled) destacar(mostrarBtn.dataset.sel); return; }
      const link = alvo.closest(".aj-link");
      if (link) {
        buscar(link.dataset.tipo, link.dataset.chave).then((a) => { if (a) mostrar(a, true); });
        return;
      }
      const ir = alvo.closest(".aj-ir");
      if (ir) { irPara(ir.dataset.tipo, ir.dataset.chave); return; }
      const chip = alvo.closest(".aj-chip");
      if (chip) { $(chip.dataset.alvo)?.scrollIntoView({ block: "start", behavior: "smooth" }); return; }
      const nivel = alvo.closest(".aj-nivel");
      if (nivel) { nivelAtivo = Number(nivel.dataset.i); desenharNivel(); }
    });
  }

  /* ---------- Central de ajuda (tela Ajuda) ---------- */

  let indice = null;

  function cartao(i) {
    return `<button type="button" class="aj-card" data-tipo="${esc(i.tipo)}" data-chave="${esc(i.chave)}"
      data-busca="${esc(i.busca)}"><strong>${esc(i.titulo)}</strong><span>${esc(i.resumo.replace(/\*\*/g, "").replace(/`/g, ""))}</span></button>`;
  }

  function filtrarCentral() {
    const q = ($("aj-busca").value || "").trim().toLowerCase();
    const sem = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    let total = 0;
    document.querySelectorAll("#sec-ajuda .aj-card").forEach((c) => {
      const ok = !q || sem(c.dataset.busca).includes(sem(q));
      c.hidden = !ok;
      if (ok) total++;
    });
    document.querySelectorAll("#sec-ajuda .aj-grupo").forEach((g) => {
      g.hidden = !g.querySelector(".aj-card:not([hidden])");
    });
    $("aj-vazio").hidden = total > 0;
  }

  async function carregarCentral() {
    const alvo = $("aj-lista-telas");
    if (!alvo || alvo.dataset.pronto === "1") return;
    try {
      const r = await fetch(`${API}/indice`);
      if (!r.ok) throw new Error();
      indice = await r.json();
    } catch (e) {
      alvo.innerHTML = '<p class="aj-resumo">Não foi possível carregar o índice da ajuda.</p>';
      return;
    }
    alvo.innerHTML = indice.telas.map(cartao).join("");
    $("aj-lista-automacoes").innerHTML = indice.automacoes.map((g) =>
      `<div class="aj-grupo"><h4>${esc(g.rotulo)}</h4><div class="aj-cards">${g.itens.map(cartao).join("")}</div></div>`).join("");
    $("aj-lista-config").innerHTML = indice.configuracoes.map(cartao).join("");
    alvo.dataset.pronto = "1";
    $("aj-busca").addEventListener("input", filtrarCentral);
    document.querySelectorAll("#sec-ajuda .aj-card").forEach((c) =>
      c.addEventListener("click", () => abrirItem(c.dataset.tipo, c.dataset.chave)));
  }

  function observarCentral() {
    const sec = $("sec-ajuda");
    if (!sec) return;
    new MutationObserver(() => { if (sec.classList.contains("active")) carregarCentral(); })
      .observe(sec, { attributes: true, attributeFilter: ["class"] });
  }

  /* ---------- início ---------- */

  window.abrirAjuda = abrir;
  window.fecharAjuda = fechar;
  ligar();
  observarCentral();
})();
