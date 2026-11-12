/* ============================================================
   AUTO SERE — planilhas.js
   Tela "Planilhas do Drive": gerenciador centralizado de planilhas (Google Sheets,
   Excel .xlsx, LibreOffice .ods): cadastro, planilha vigente de cada uso e criação a partir dos modelos do sistema.
   Tudo fica dentro de uma IIFE para não colidir com os globais do
   app.js; só `carregarPlanilhas` é exposta (chamada por
   irPara("planilhas") no app.js).
   API: /web/api/planilhas/...  (regras em src/comum/planilhas_registro.py)
   ============================================================ */
(function () {
  "use strict";

  const API = "/web/api/planilhas";
  const POR_PAGINA = 20;
  const PREFIXO_LINK = "https://docs.google.com/spreadsheets/";

  const st = {
    q: "", status: "", categoria: "", ordem: "id", dir: "asc",
    itens: [], total: 0, proximo: null,
    resumo: { total: 0, ativas: 0, inativas: 0 },
    finalidades: {}, infoFin: {}, plataformas: {},                                        // valor → nome ("parecer_infantil" → "Pareceres do Infantil")
    pronto: false, req: 0,
  };

  const $ = (id) => document.getElementById(id);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const aviso = (msg) => { if (typeof toast === "function") toast(msg); };

  async function api(metodo, caminho = "", corpo) {
    const opcoes = { method: metodo, headers: {} };
    if (corpo !== undefined) {
      opcoes.headers["Content-Type"] = "application/json";
      opcoes.body = JSON.stringify(corpo);
    }
    const res = await fetch(API + caminho, opcoes);
    let dados = null;
    try { dados = await res.json(); } catch (e) { /* resposta sem corpo JSON (servidor fora do ar, por exemplo) */ }
    if (!res.ok) throw new Error((dados && (dados.erro || dados.mensagem)) || `Erro ${res.status} ao falar com o servidor`);
    return dados;
  }

  function dataBr(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(iso || ""));
    return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : "";
  }

  // ---------------------------------------------------------------- lista

  async function carregar(reiniciar) {
    const meu = ++st.req;                                   // respostas antigas (busca digitada rápido) são descartadas
    const inicio = reiniciar ? 0 : st.itens.length;
    const p = new URLSearchParams({
      q: st.q, status: st.status, categoria: st.categoria, ordem: st.ordem, dir: st.dir, limite: POR_PAGINA, inicio,
    });
    try {
      const d = await api("GET", "?" + p.toString());
      if (meu !== st.req) return;
      st.itens = reiniciar ? d.itens : st.itens.concat(d.itens);
      st.total = d.total;
      st.proximo = d.proximo;
      st.resumo = d.resumo || st.resumo;
      desenhar();
    } catch (e) {
      if (meu !== st.req) return;
      $("pl-corpo").innerHTML = `<tr><td colspan="7" class="empty" style="color:var(--rose)">${esc(e.message)}</td></tr>`;
      $("pl-contagem").textContent = "";
      $("pl-mais").hidden = true;
    }
  }

  function desenhar() {
    const filtrando = st.q || st.status || st.categoria;
    if (!st.itens.length) {
      $("pl-corpo").innerHTML = `<tr><td colspan="7" class="empty">${filtrando
        ? "Nenhuma planilha encontrada para essa busca."
        : "Nenhuma planilha cadastrada ainda. Use “Nova planilha” para cadastrar a primeira."}</td></tr>`;
    } else {
      $("pl-corpo").innerHTML = st.itens.map(linha).join("");
    }
    $("pl-contagem").textContent = st.total ? `Mostrando ${st.itens.length} de ${st.total}` : "";
    $("pl-mais").hidden = st.proximo === null;
    $("pl-leg-ativas").textContent = st.resumo.ativas;
    $("pl-leg-inativas").textContent = st.resumo.inativas;
    document.querySelectorAll("#pl-tabela thead th[data-ordem]").forEach((th) => {
      th.classList.remove("sort-asc", "sort-desc");
      if (th.dataset.ordem === st.ordem) th.classList.add(st.dir === "asc" ? "sort-asc" : "sort-desc");
    });
  }

  function linha(p) {
    const linkSeguro = String(p.link || "").startsWith(PREFIXO_LINK);
    const ativa = p.status === "ativa";
    const origem = p.origem === "sistema" ? "criada pelo sistema" : "cadastrada à mão";
    const natureza = { externa: "externa (da Secretaria)", criada_de_modelo: "criada de modelo", cadastrada: "" }[p.natureza] || "";
    const plat = st.plataformas[p.plataforma] || p.plataforma;
    const uso = (p.finalidade ? `${st.finalidades[p.finalidade] || p.finalidade}${p.turma ? " · " + p.turma : ""}` : "")
      + `${p.finalidade ? " · " : ""}${plat}${natureza ? " · " + natureza : ""}`;
    return `<tr data-id="${esc(p.id)}">
      <td class="td-mono">${esc(p.id)}</td>
      <td class="td-name" title="${esc(p.observacao || "")}">${esc(p.nome)}<small>${esc(uso ? uso + " · " : "")}${origem}</small></td>
      <td>${esc(p.categoria)}</td>
      <td>${linkSeguro
        ? `<a class="pl-link" href="${esc(p.link)}" target="_blank" rel="noopener noreferrer" title="${esc(p.link)}">${esc(p.link)}</a>`
        : esc(p.caminho || p.link)}</td>
      <td><span class="badge ${ativa ? "bg-lime" : "bg-muted"}">${ativa ? "Ativa" : "Inativa"}</span></td>
      <td class="td-mono">${esc(dataBr(p.atualizado_em))}</td>
      <td><div class="row-actions">
        ${!ativa && p.finalidade ? `<button class="btn-sm" type="button" data-acao="ativar" title="Passar a usar esta planilha (a atual do mesmo uso fica inativa)" style="padding:6px 9px;font-size:.72rem">Usar esta</button>` : ""}
        <button class="btn-sm" type="button" data-acao="copiar" title="Copiar o link ou caminho da planilha" style="padding:6px 9px;font-size:.72rem">Copiar</button>
        <button class="btn-sm" type="button" data-acao="editar" style="padding:6px 9px;font-size:.72rem">Editar</button>
        <button class="btn-sm" type="button" data-acao="remover" style="padding:6px 9px;font-size:.72rem">Remover</button>
      </div></td>
    </tr>`;
  }

  async function carregarCategorias() {
    try {
      const d = await api("GET", "/categorias");
      const select = $("pl-filtro-categoria");
      const atual = st.categoria;
      select.innerHTML = '<option value="">Todas as categorias</option>' +
        d.usadas.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
      select.value = d.usadas.includes(atual) ? atual : "";
      st.categoria = select.value;
      return d.todas;
    } catch (e) {
      return [];
    }
  }

  // ---------------------------------------------------------------- formulário (cadastrar / editar)

  async function carregarFinalidades() {
    try {
      const d = await api("GET", "/finalidades");
      st.finalidades = Object.fromEntries(d.finalidades.map((f) => [f.valor, f.nome]));
      st.infoFin = Object.fromEntries(d.finalidades.map((f) => [f.valor, f]));
      st.plataformas = Object.fromEntries((d.plataformas || []).map((p) => [p.valor, p.nome]));
      return d;
    } catch (e) {
      return { finalidades: [], turmas: [], plataformas: [] };
    }
  }

  async function abrirFormulario(item) {
    const todas = await carregarCategorias();
    const fin = await carregarFinalidades();
    const editando = !!item;
    const fundo = document.createElement("div");
    fundo.className = "modal-overlay";
    fundo.innerHTML = `<div class="modal-card" role="dialog" aria-modal="true" aria-label="${editando ? "Editar planilha" : "Nova planilha"}">
      <h3>${editando ? `Editar planilha (id ${esc(item.id)})` : "Nova planilha"}</h3>
      <div class="field"><label>Nome da planilha</label>
        <input type="text" id="pl-f-nome" maxlength="250" placeholder="Pareceres do Infantil 2026" autocomplete="off"></div>
      <div class="field"><label>Plataforma</label>
        <select id="pl-f-plat">${(fin.plataformas || []).map((p) => `<option value="${esc(p.valor)}">${esc(p.nome)}</option>`).join("")}</select></div>
      <div class="field" id="pl-f-link-campo"><label>Link da planilha (ou só o ID)</label>
        <input type="text" id="pl-f-link" placeholder="https://docs.google.com/spreadsheets/d/…" autocomplete="off"></div>
      <div class="field" id="pl-f-caminho-campo" hidden><label>Caminho do arquivo no computador</label>
        <input type="text" id="pl-f-caminho" placeholder="C:\\Planilhas\\arquivo.xlsx" autocomplete="off"></div>
      <div class="form-linha">
        <div class="field"><label>Categoria</label>
          <input type="text" id="pl-f-cat" list="pl-f-categorias" maxlength="60" placeholder="Pareceres do Infantil" autocomplete="off">
          <datalist id="pl-f-categorias">${todas.map((c) => `<option value="${esc(c)}"></option>`).join("")}</datalist></div>
        <div class="field"><label>Situação</label>
          <select id="pl-f-status"><option value="ativa">Ativa</option><option value="inativa">Inativa</option></select></div>
      </div>
      <div class="form-linha">
        <div class="field"><label>Finalidade no sistema</label>
          <select id="pl-f-fin"><option value="">Só guardar a planilha</option>${fin.finalidades.map((f) => `<option value="${esc(f.valor)}">${esc(f.nome)}</option>`).join("")}</select></div>
        <div class="field" id="pl-f-turma-campo" hidden><label>Turma (igual ao turmas.json)</label>
          <input type="text" id="pl-f-turma" list="pl-f-turmas" maxlength="100" placeholder="INFANTIL 4 Integral A" autocomplete="off">
          <datalist id="pl-f-turmas">${fin.turmas.map((c) => `<option value="${esc(c)}"></option>`).join("")}</datalist></div>
      </div>
      <div class="cep-msg" id="pl-f-fin-ajuda" style="margin:-4px 0 14px" hidden>As automações usam a planilha <b>ativa</b> de cada uso (e turma). Para trocar de planilha, use “Usar esta” na nova.</div>
      <div class="field"><label>Observação (opcional)</label>
        <textarea id="pl-f-obs" rows="2" maxlength="500" placeholder="Para que serve, quem usa…"></textarea></div>
      <div class="pl-erro" id="pl-f-erro" role="alert"></div>
      <div class="modal-acoes">
        <button class="btn-sm" type="button" id="pl-f-cancelar">Cancelar</button>
        <button class="btn-primary" type="button" id="pl-f-salvar">${editando ? "Salvar alterações" : "Cadastrar"}</button>
      </div>
    </div>`;
    document.body.appendChild(fundo);

    const campo = (id) => fundo.querySelector("#" + id);
    // Valores pelo DOM (e não dentro do HTML): nada do que foi digitado vira marcação.
    if (editando) {
      campo("pl-f-nome").value = item.nome;
      campo("pl-f-plat").value = item.plataforma || "google_sheets";
      campo("pl-f-link").value = item.link || "";
      campo("pl-f-caminho").value = item.caminho || "";
      campo("pl-f-cat").value = item.categoria;
      campo("pl-f-status").value = item.status;
      campo("pl-f-obs").value = item.observacao || "";
      campo("pl-f-fin").value = item.finalidade || "";
      campo("pl-f-turma").value = item.turma || "";
    }
    const mostrarTurma = () => {
      const f = campo("pl-f-fin").value;
      campo("pl-f-turma-campo").hidden = !(f && (st.infoFin[f] || {}).por_turma);
      campo("pl-f-fin-ajuda").hidden = !f;
    };
    const mostrarOrigem = () => {
      const local = !!((fin.plataformas || []).find((p) => p.valor === campo("pl-f-plat").value) || {}).local;
      campo("pl-f-link-campo").hidden = local;
      campo("pl-f-caminho-campo").hidden = !local;
    };
    campo("pl-f-fin").addEventListener("change", mostrarTurma);
    campo("pl-f-plat").addEventListener("change", mostrarOrigem);
    mostrarTurma();
    mostrarOrigem();
    const fechar = () => { fundo.remove(); document.removeEventListener("keydown", aoTeclar); };
    const aoTeclar = (ev) => { if (ev.key === "Escape") fechar(); };
    document.addEventListener("keydown", aoTeclar);
    fundo.addEventListener("mousedown", (ev) => { if (ev.target === fundo) fechar(); });
    campo("pl-f-cancelar").addEventListener("click", fechar);
    campo("pl-f-nome").focus();

    const salvar = async () => {
      const corpo = {
        nome: campo("pl-f-nome").value.trim(),
        plataforma: campo("pl-f-plat").value,
        link: campo("pl-f-link-campo").hidden ? "" : campo("pl-f-link").value.trim(),
        caminho: campo("pl-f-caminho-campo").hidden ? "" : campo("pl-f-caminho").value.trim(),
        categoria: campo("pl-f-cat").value.trim(),
        status: campo("pl-f-status").value,
        observacao: campo("pl-f-obs").value.trim(),
        finalidade: campo("pl-f-fin").value,
        turma: campo("pl-f-turma-campo").hidden ? "" : campo("pl-f-turma").value.trim(),
      };
      const erro = campo("pl-f-erro");
      erro.textContent = "";
      if (!corpo.nome) { erro.textContent = "Informe o nome da planilha."; return; }
      if (!corpo.link && !corpo.caminho) { erro.textContent = "Informe o link (Google) ou o caminho do arquivo."; return; }
      if (!campo("pl-f-turma-campo").hidden && !corpo.turma) { erro.textContent = "Informe a turma desta planilha."; return; }
      const botao = campo("pl-f-salvar");
      botao.disabled = true;
      try {
        const resp = editando ? await api("PUT", `/${item.id}`, corpo) : await api("POST", "", corpo);
        fechar();
        aviso(resp.mensagem || "Salvo");
        await carregarCategorias();
        await carregar(true);
      } catch (e) {
        erro.textContent = e.message;            // fica aberto para corrigir (ex.: "já está cadastrada como…")
        botao.disabled = false;
      }
    };
    campo("pl-f-salvar").addEventListener("click", salvar);
    fundo.querySelectorAll("input[type=text]").forEach((i) => i.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); salvar(); }
    }));
  }

  async function abrirCriarDeModelo() {
    let d;
    try {
      d = await api("GET", "/modelos");
    } catch (e) {
      aviso(e.message);
      return;
    }
    const fundo = document.createElement("div");
    fundo.className = "modal-overlay";
    fundo.innerHTML = `<div class="modal-card" role="dialog" aria-modal="true" aria-label="Criar planilha de modelo">
      <h3>Criar planilha a partir de um modelo</h3>
      <div class="field"><label>Modelo</label>
        <select id="pm-modelo">${d.modelos.map((m) => `<option value="${esc(m.chave)}">${esc(m.nome)}</option>`).join("")}</select></div>
      <div class="cep-msg" id="pm-desc" style="margin:-4px 0 14px"></div>
      <div class="field"><label>Criar em</label>
        <select id="pm-plat">${d.plataformas.map((p) => `<option value="${esc(p.valor)}"${p.indisponivel ? " disabled" : ""}>${esc(p.nome)}${p.indisponivel ? " (indisponível neste computador)" : ""}</option>`).join("")}</select></div>
      <div class="field" id="pm-turma-campo" hidden><label>Turma</label>
        <select id="pm-turma">${d.turmas.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("")}</select></div>
      <div class="field"><label>Nome da planilha (opcional)</label>
        <input type="text" id="pm-nome" maxlength="250" placeholder="em branco = modelo + turma + ano" autocomplete="off"></div>
      <div class="field"><label><input type="checkbox" id="pm-vigente"> Passar a usar a nova planilha (a atual do mesmo uso fica inativa)</label></div>
      <div class="pl-erro" id="pm-erro" role="alert"></div>
      <div class="modal-acoes">
        <button class="btn-sm" type="button" id="pm-cancelar">Cancelar</button>
        <button class="btn-primary" type="button" id="pm-criar">Criar e cadastrar</button>
      </div>
    </div>`;
    document.body.appendChild(fundo);
    const c = (id) => fundo.querySelector("#" + id);
    const atual = () => d.modelos.find((m) => m.chave === c("pm-modelo").value) || {};
    const atualizar = () => {
      c("pm-desc").textContent = atual().descricao || "";
      c("pm-turma-campo").hidden = !atual().uma_turma;
    };
    c("pm-modelo").addEventListener("change", atualizar);
    atualizar();
    const fechar = () => fundo.remove();
    c("pm-cancelar").addEventListener("click", fechar);
    fundo.addEventListener("mousedown", (ev) => { if (ev.target === fundo) fechar(); });
    c("pm-criar").addEventListener("click", async () => {
      const botao = c("pm-criar");
      c("pm-erro").textContent = "";
      botao.disabled = true;
      try {
        const resp = await api("POST", "/criar-de-modelo", {
          modelo: c("pm-modelo").value, plataforma: c("pm-plat").value, nome: c("pm-nome").value.trim(),
          turma: atual().uma_turma ? c("pm-turma").value : "", tornar_vigente: c("pm-vigente").checked,
        });
        fechar();
        aviso([resp.mensagem].concat(resp.avisos || []).join(" "));
        await carregarCategorias();
        await carregar(true);
      } catch (e) {
        c("pm-erro").textContent = e.message;
        botao.disabled = false;
      }
    });
  }

  async function aoClicarNaTabela(ev) {
    const botao = ev.target.closest("button[data-acao]");
    if (!botao) return;
    const tr = botao.closest("tr[data-id]");
    const item = st.itens.find((p) => String(p.id) === tr.dataset.id);
    if (!item) return;
    if (botao.dataset.acao === "editar") {
      abrirFormulario(item);
    } else if (botao.dataset.acao === "copiar") {
      try {
        await navigator.clipboard.writeText(item.caminho || item.link);
        aviso(item.caminho ? "Caminho copiado" : "Link copiado");
      } catch (e) {
        aviso("Não foi possível copiar: selecione o link e copie à mão.");
      }
    } else if (botao.dataset.acao === "ativar") {
      botao.disabled = true;
      try {
        const resp = await api("POST", `/${item.id}/ativar`);
        aviso(resp.mensagem || "Planilha em uso");
        await carregar(true);
      } catch (e) {
        botao.disabled = false;
        aviso(e.message);
      }
    } else if (botao.dataset.acao === "remover") {
      if (!confirm(`Remover “${item.nome}” do cadastro?\nA planilha em si não é apagada (Google ou arquivo); só a referência sai desta lista.`)) return;
      botao.disabled = true;
      try {
        const resp = await api("DELETE", `/${item.id}`);
        aviso(resp.mensagem || "Removida");
        await carregarCategorias();
        await carregar(true);
      } catch (e) {
        botao.disabled = false;
        aviso(e.message);
      }
    }
  }

  // ---------------------------------------------------------------- inicialização (uma vez)

  function iniciar() {
    if (st.pronto) return;
    st.pronto = true;
    let espera = null;
    $("pl-busca").addEventListener("input", (ev) => {
      clearTimeout(espera);
      espera = setTimeout(() => { st.q = ev.target.value.trim(); carregar(true); }, 250);
    });
    $("pl-filtro-status").addEventListener("change", (ev) => { st.status = ev.target.value; carregar(true); });
    $("pl-filtro-categoria").addEventListener("change", (ev) => { st.categoria = ev.target.value; carregar(true); });
    $("pl-mais").addEventListener("click", () => carregar(false));
    $("pl-nova").addEventListener("click", () => abrirFormulario(null));
    $("pl-modelo").addEventListener("click", abrirCriarDeModelo);
    $("pl-corpo").addEventListener("click", aoClicarNaTabela);
    document.querySelectorAll("#pl-tabela thead th[data-ordem]").forEach((th) => {
      const ordenar = () => {
        st.dir = st.ordem === th.dataset.ordem && st.dir === "asc" ? "desc" : "asc";
        st.ordem = th.dataset.ordem;
        carregar(true);
      };
      th.addEventListener("click", ordenar);
      th.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); ordenar(); } });
    });
  }

  window.carregarPlanilhas = async function () {
    iniciar();
    await Promise.all([carregarCategorias(), carregarFinalidades()]);
    await carregar(true);
  };
})();
