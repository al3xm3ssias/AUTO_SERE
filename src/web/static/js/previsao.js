/* ============================================================
   AUTO SERE — previsao.js
   Módulo "Previsão <ano letivo + 1>" (GET /web/api/previsao). Três visões:
     · Lista geral     rematriculados (já na turma do ANO QUE VEM) + novos da pré-matrícula, com filtro e agrupamento por turma;
     · Por turma       uma turma por vez: quem vem de onde, novos, e quem era esperado nela e ainda não rematriculou;
     · Ficaram de fora matriculados hoje que não rematricularam (transferidos do ano ficam de fora), com o motivo provável.
   Tudo numa IIFE; só `carregarPrevisao` é exposta (chamada por irPara("previsao")).
   ============================================================ */
(function () {
  "use strict";

  const estado = {
    view: "lista", aba: "todos", busca: "", turma: "", agrupar: true,
    turmaSel: "", foraCat: "fora", foraBusca: "", foraTurma: "", dados: null, geo: null, geoBusca: "", geoTurma: "",
  };
  let ligada = false;

  const $ = (id) => document.getElementById(id);
  const esc = (v) => escaparHtml(v);
  const fora = () => (estado.dados && estado.dados.fora) || { disponivel: false, linhas: [], resumo_series: [], contagem: {} };

  const CATEGORIAS = {
    sem_registro: { rotulo: "Sem registro", cls: "bg-rose" },
    erro_rematricula: { rotulo: "Erro na rematrícula", cls: "bg-amber" },
    outra_escola: { rotulo: "Outra escola", cls: "bg-violet" },
    cancelou: { rotulo: "Cancelou", cls: "bg-muted" },
    concluinte: { rotulo: "Concluinte", cls: "bg-cyan" },
  };

  /* ───────────────────────── lista geral ───────────────────────── */

  function filtradas() {
    if (!estado.dados) return [];
    const q = semAcento(estado.busca.trim());
    return estado.dados.linhas.filter((l) => {
      if (estado.aba !== "todos" && l.tipo !== estado.aba) return false;
      if (estado.turma && l.turma !== estado.turma) return false;
      if (!q) return true;
      return [l.nome, l.cgm, l.cpf, l.turma, l.turma_atual, l.responsavel].some((c) => semAcento(c).includes(q));
    });
  }

  function rotuloSituacao(l) {
    if (l.tipo === "rematriculado") return badge("Rematriculado", "bg-lime");
    if (l.situacao === "matriculado") return badge("Vaga confirmada", "bg-cyan");
    return badge("Aguardando", "bg-amber");
  }

  function linhaAluno(l) {
    const aviso = l.ja_e_aluno && l.tipo === "novo"
      ? ` <span class="badge bg-muted" title="Já consta como aluno da escola neste ano, sem rematrícula confirmada">já é aluno</span>` : "";
    const origem = l.tipo === "novo" && (l.escola_origem || l.turma_origem)
      ? `<small>vem de ${esc([l.turma_origem, l.escola_origem].filter(Boolean).join(" · "))}</small>` : "";
    const sub = l.tipo === "rematriculado" && l.turma_atual
      ? `<small>hoje: ${esc(l.turma_atual)}</small>`
      : (l.posicao ? `<small>posição ${esc(l.posicao)}</small>` : "");
    return `<tr>
        <td class="td-name">${esc(l.nome || "—")}${aviso}${origem}</td>
        <td>${l.tipo === "novo" ? badge("Novo", "bg-amber") : badge("Rematrícula", "bg-lime")}</td>
        <td>${esc(l.turma || "—")}${sub}</td>
        <td class="td-mono">${esc(l.cgm || l.cpf || "—")}</td>
        <td>${esc(l.nascimento || "—")}</td>
        <td>${rotuloSituacao(l)}</td>
        <td>${esc(l.responsavel || "—")}${l.telefone ? `<small>${esc(l.telefone)}</small>` : ""}</td>
      </tr>`;
  }

  function contarTipos(linhas) {
    const novos = linhas.filter((l) => l.tipo === "novo").length;
    return `${linhas.length - novos} rematr. · ${novos} novos`;
  }

  function desenharLinhas() {
    const linhas = filtradas();
    $("pv-cnt").textContent = linhas.length;
    const vazio = $("pv-vazio");
    if (!linhas.length) {
      $("pv-tbody").innerHTML = "";
      $("pv-vazio-msg").textContent = estado.dados.linhas.length ? "Nenhum resultado."
        : "Nenhum aluno na previsão ainda. Rode a rematrícula e a pré-matrícula do próximo ano.";
      vazio.style.display = "";
      return;
    }
    vazio.style.display = "none";
    let html = "";
    let ultima = null;
    for (const l of linhas) {
      if (estado.agrupar && l.turma !== ultima) {
        ultima = l.turma;
        const doGrupo = linhas.filter((x) => x.turma === l.turma);
        html += `<tr class="pv-grupo"><td colspan="7">${esc(l.turma || "Sem turma")}<span>${doGrupo.length} aluno(s) · ${contarTipos(doGrupo)}</span></td></tr>`;
      }
      html += linhaAluno(l);
    }
    $("pv-tbody").innerHTML = html;
  }

  function preencherFiltroTurma(selectId, nomes, valorAtual, rotuloTodas) {
    const el = $(selectId);
    el.innerHTML = `<option value="">${esc(rotuloTodas)}</option>` +
      nomes.map((n) => `<option value="${esc(n)}"${n === valorAtual ? " selected" : ""}>${esc(n)}</option>`).join("");
  }

  /* ───────────────────────── por turma ───────────────────────── */

  function foraPorTurmaPrevista() {
    const mapa = {};
    fora().linhas.filter((l) => l.categoria !== "concluinte").forEach((l) => {
      (mapa[l.turma_prevista] = mapa[l.turma_prevista] || []).push(l);
    });
    return mapa;
  }

  function desenharTurmas() {
    const turmas = estado.dados.turmas || [];
    if (!turmas.length) {
      $("pv-tiles").innerHTML = "";
      $("pv-turma-detalhe").innerHTML = `<div class="empty"><span>Nenhuma turma na previsão ainda. Rode a rematrícula e a pré-matrícula do próximo ano.</span></div>`;
      return;
    }
    if (!turmas.some((t) => t.turma === estado.turmaSel)) estado.turmaSel = turmas[0].turma;
    const faltam = foraPorTurmaPrevista();

    $("pv-tiles").innerHTML = turmas.map((t) => {
      const f = (faltam[t.turma] || []).length;
      return `<button type="button" class="pv-tile${t.turma === estado.turmaSel ? " active" : ""}" data-turma="${esc(t.turma)}">
        <span class="pv-tile-nome">${esc(t.turma)}</span>
        <span class="pv-tile-total">${t.total}</span>
        <span class="pv-tile-sub">${t.rematriculados} rematr. · ${t.novos} novos</span>
        ${f ? `<span class="pv-tile-fora">+${f} ainda sem rematrícula</span>` : ""}
      </button>`;
    }).join("");
    $("pv-tiles").querySelectorAll(".pv-tile").forEach((b) => b.addEventListener("click", () => {
      estado.turmaSel = b.dataset.turma;
      desenharTurmas();
    }));

    const t = turmas.find((x) => x.turma === estado.turmaSel);
    const alunos = estado.dados.linhas.filter((l) => l.turma === t.turma);
    const pendentes = faltam[t.turma] || [];
    const origens = Object.entries(t.origens || {}).map(([o, n]) => badge(`${n} vindos de ${o}`, "bg-lime")).join("");
    const novosInfo = (t.novos_matriculados ? badge(`${t.novos_matriculados} novos com vaga`, "bg-cyan") : "")
      + (t.novos_pendentes ? badge(`${t.novos_pendentes} novos aguardando`, "bg-amber") : "");

    const linhasFora = pendentes.map((l) => `<tr>
        <td class="td-name">${esc(l.nome || "—")}</td>
        <td>${esc(l.turma_atual || "—")}</td>
        <td class="td-mono">${esc(l.cgm || "—")}</td>
        <td>${esc(l.nascimento || "—")}</td>
        <td>${badge((CATEGORIAS[l.categoria] || {}).rotulo || l.categoria, (CATEGORIAS[l.categoria] || {}).cls || "bg-muted")}<small>${esc(l.motivo)}</small></td>
        <td>${esc(l.responsavel || "—")}${l.telefone ? `<small>${esc(l.telefone)}</small>` : ""}</td>
      </tr>`).join("");

    $("pv-turma-detalhe").innerHTML = `
      <div class="card-header">
        <span data-icon="users" style="color:var(--txt3)"></span>
        <span class="card-title">${esc(t.turma)}</span>
        <span class="card-header-badge">${t.total}</span>
      </div>
      <div class="card-body">
        <p class="campo-ajuda" style="margin:0">${esc(contarTipos(alunos))}${pendentes.length ? ` · ${pendentes.length} esperado(s) que ainda não rematricularam` : ""}</p>
        <div class="pv-origens">${origens}${novosInfo}</div>
      </div>
      <div class="card-body no-pad">
        <div class="tbl-wrap" style="border:none; border-radius:0">
          <table>
            <thead><tr><th>Aluno</th><th>Tipo</th><th>Turma ${esc(estado.dados.ano)}</th><th>CGM / CPF</th><th>Nascimento</th><th>Situação</th><th>Responsável</th></tr></thead>
            <tbody>${alunos.map(linhaAluno).join("")}</tbody>
          </table>
        </div>
        ${pendentes.length ? `
        <div class="pv-detalhe-sep">Esperados nesta turma que não rematricularam (${pendentes.length})</div>
        <div class="tbl-wrap" style="border:none; border-radius:0">
          <table>
            <thead><tr><th>Aluno</th><th>Turma hoje</th><th>CGM</th><th>Nascimento</th><th>Motivo provável</th><th>Responsável</th></tr></thead>
            <tbody>${linhasFora}</tbody>
          </table>
        </div>` : ""}
      </div>`;
  }

  /* ───────────────────────── ficaram de fora ───────────────────────── */

  function foraFiltradas() {
    const q = semAcento(estado.foraBusca.trim());
    return fora().linhas.filter((l) => {
      if (estado.foraCat === "fora" ? l.categoria === "concluinte" : l.categoria !== estado.foraCat) return false;
      if (estado.foraTurma && l.turma_atual !== estado.foraTurma) return false;
      if (!q) return true;
      return [l.nome, l.cgm, l.turma_atual, l.responsavel, l.motivo].some((c) => semAcento(c).includes(q));
    });
  }

  function desenharFora() {
    const f = fora();
    const c = f.contagem || {};
    $("pv-fora-n").textContent = f.disponivel ? `(${c.total || 0})` : "";
    if (!f.disponivel) {
      $("pv-fora-series").innerHTML = "";
      $("pv-fora-pills").innerHTML = "";
      $("pv-fora-cnt").textContent = "0";
      $("pv-fora-tbody").innerHTML = "";
      $("pv-fora-vazio-msg").textContent = "Não há turmas.json deste ano. Rode a coleta de turmas para comparar.";
      $("pv-fora-vazio").style.display = "";
      return;
    }
    $("pv-fora-base").textContent = `${c.ativos || 0} matriculados hoje`;

    $("pv-fora-series").innerHTML = (f.resumo_series || []).map((s) => {
      const esperados = s.ativos - s.concluintes;
      const concluinte = s.concluintes > 0 && s.fora === 0 && s.na_previsao === 0;
      const pct = esperados > 0 ? Math.round((s.na_previsao / esperados) * 100) : null;
      return `<tr>
        <td class="td-name">${esc(s.serie)}${concluinte ? badge("concluintes", "bg-cyan") : ""}</td>
        <td>${s.ativos}</td><td>${s.na_previsao}</td>
        <td>${s.fora ? `<strong style="color:var(--rose)">${s.fora}</strong>` : "0"}</td>
        <td>${concluinte || pct === null ? "—" : `<span class="pv-barra"><i style="width:${pct}%"></i></span>${pct}%`}</td>
      </tr>`;
    }).join("");

    const pills = [["fora", `Todos (${c.total || 0})`], ["sem_registro", `Sem registro (${c.sem_registro || 0})`],
      ["erro_rematricula", `Erro na rematrícula (${c.erro_rematricula || 0})`], ["outra_escola", `Outra escola (${c.outra_escola || 0})`],
      ["cancelou", `Cancelou (${c.cancelou || 0})`], ["concluinte", `Concluintes (${c.concluintes || 0})`]];
    $("pv-fora-pills").innerHTML = pills.map(([k, r]) => `<button type="button" class="pill${k === estado.foraCat ? " active" : ""}" data-foracat="${k}">${esc(r)}</button>`).join("");
    $("pv-fora-pills").querySelectorAll("[data-foracat]").forEach((b) => b.addEventListener("click", () => { estado.foraCat = b.dataset.foracat; desenharFora(); }));

    const turmasHoje = [...new Set(f.linhas.map((l) => l.turma_atual))];
    preencherFiltroTurma("pv-fora-turma", turmasHoje, estado.foraTurma, "Todas as turmas de hoje");

    const linhas = foraFiltradas();
    $("pv-fora-cnt").textContent = linhas.length;
    if (!linhas.length) {
      $("pv-fora-tbody").innerHTML = "";
      $("pv-fora-vazio-msg").textContent = f.linhas.length ? "Nenhum resultado." : "Todos os alunos matriculados estão na previsão.";
      $("pv-fora-vazio").style.display = "";
      return;
    }
    $("pv-fora-vazio").style.display = "none";
    $("pv-fora-tbody").innerHTML = linhas.map((l) => {
      const cat = CATEGORIAS[l.categoria] || { rotulo: l.categoria, cls: "bg-muted" };
      return `<tr>
        <td class="td-name">${esc(l.nome || "—")}</td>
        <td>${esc(l.turma_atual || "—")}</td>
        <td>${esc(l.turma_prevista || "—")}</td>
        <td class="td-mono">${esc(l.cgm || "—")}</td>
        <td>${esc(l.nascimento || "—")}</td>
        <td>${badge(cat.rotulo, cat.cls)}${l.categoria === "sem_registro" ? "" : `<small>${esc(l.motivo)}</small>`}</td>
        <td>${esc(l.responsavel || "—")}${l.telefone ? `<small>${esc(l.telefone)}</small>` : ""}</td>
      </tr>`;
    }).join("");
  }

  /* ───────────────────────── exportação ───────────────────────── */

  function baixarCsv(nomeArquivo, cabecalho, corpo) {
    if (!corpo.length) { toast("Nada para exportar."); return; }
    const celula = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = "\uFEFF" + [cabecalho.map(celula).join(";"), ...corpo.map((l) => l.map(celula).join(";"))].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = nomeArquivo;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  const rotuloPrevisao = (l) => (l.tipo === "rematriculado" ? "Rematriculado" : l.situacao === "matriculado" ? "Novo - vaga confirmada" : "Novo - aguardando");
  const CAB_PREVISAO = ["Nome", "Tipo", "Turma", "Turma hoje", "CGM", "CPF", "Nascimento", "Situação", "Responsável", "Telefone"];
  const linhaCsv = (l) => [l.nome, l.tipo === "novo" ? "Novo" : "Rematriculado", l.turma, l.turma_atual, l.cgm, l.cpf, l.nascimento, rotuloPrevisao(l), l.responsavel, l.telefone];

  function exportar() {
    const ano = estado.dados.ano;
    if (estado.view === "geo") {
      baixarCsv(`previsao-${ano}-direcionados-geo.csv`, ["Turma", "Aluno", "CGM", "Responsável"],
        geoFiltrados().map((a) => [geoRotuloTurma(a), a.nome, a.cgm, a.responsavel]));
    } else if (estado.view === "fora") {
      baixarCsv(`previsao-${ano}-ficaram-de-fora.csv`,
        ["Nome", "Turma hoje", "Iria para", "CGM", "Nascimento", "Motivo", "Responsável", "Telefone"],
        foraFiltradas().map((l) => [l.nome, l.turma_atual, l.turma_prevista, l.cgm, l.nascimento, (CATEGORIAS[l.categoria] || {}).rotulo + " — " + l.motivo, l.responsavel, l.telefone]));
    } else if (estado.view === "turmas") {
      const alunos = estado.dados.linhas.filter((l) => l.turma === estado.turmaSel);
      baixarCsv(`previsao-${ano}-${semAcento(estado.turmaSel).replace(/[^a-z0-9]+/g, "-")}.csv`, CAB_PREVISAO, alunos.map(linhaCsv));
    } else {
      baixarCsv(`previsao-${ano}.csv`, CAB_PREVISAO, filtradas().map(linhaCsv));
    }
  }

  /* ───────────────────────── direcionados GEO (turma, aluno, CGM, responsável) ───────────────────────── */

  const geoRotuloTurma = (a) => a.turma || a.etapa || "Sem turma";
  const geoPresentes = () => ((estado.geo && estado.geo.alunos) || []).filter((a) => a.situacao_lista !== "ausente");

  function geoFiltrados() {
    const q = semAcento(estado.geoBusca);
    return geoPresentes().filter((a) => (!estado.geoTurma || geoRotuloTurma(a) === estado.geoTurma)
      && (!q || semAcento(`${a.nome} ${a.cgm} ${a.responsavel} ${geoRotuloTurma(a)}`).includes(q)));
  }

  function desenharGeo() {
    const g = estado.geo || { alunos: [], existe: false };
    const todos = geoPresentes();
    const nomes = [...new Set(todos.map(geoRotuloTurma))].sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }));
    preencherFiltroTurma("pv-geo-turma", nomes, estado.geoTurma, "Todas as turmas");
    const linhas = geoFiltrados();
    $("pv-geo-cnt").textContent = linhas.length;
    $("pv-geo-n").textContent = g.existe ? `(${todos.length})` : "";
    $("pv-geo-info").textContent = g.existe
      ? `${g.arquivo} · coletado em ${String(g.coletado_em || "—").replace("T", " ")}${g.coleta_completa === false ? " · coleta incompleta" : ""}`
      : "";
    $("pv-geo-tbody").innerHTML = linhas.map((a) => `<tr>
      <td>${esc(geoRotuloTurma(a))}</td><td class="td-name">${esc(a.nome)}</td>
      <td class="td-mono">${esc(a.cgm || "—")}</td><td>${esc(a.responsavel || "—")}</td></tr>`).join("");
    const vazio = $("pv-geo-vazio");
    vazio.style.display = linhas.length ? "none" : "";
    $("pv-geo-vazio-msg").textContent = !g.existe
      ? `Ainda não existe ${g.arquivo || "sere_sisgea"}. Rode a automação "Direcionados GEO" para coletar.`
      : "Nenhum resultado.";
  }

  /* ───────────────────────── cartões, avisos, ligações ───────────────────────── */

  function desenharCartoes(d) {
    const meta = { cyan: "cyan", lime: "lime", amber: "amber", rose: "rose" };
    $("pv-cartoes").innerHTML = (d.cartoes || []).map((c) => `
      <div class="stat-card">
        <div class="stat-card-icon">${icon(c.icone || "bolt")}</div>
        <div class="stat-lbl">${esc(c.label)}</div>
        <div class="stat-val v-${meta[c.cor] || "cyan"}">${esc(c.valor)}</div>
        ${c.sub ? `<div class="stat-sub">${esc(c.sub)}</div>` : ""}
      </div>`).join("");
  }

  function desenharAvisos(d) {
    const avisos = d.avisos || [];
    $("pv-avisos").innerHTML = avisos.length
      ? `<div class="card"><div class="card-body">${avisos.map((a) => `<p class="campo-ajuda" style="margin:2px 0">⚠️ ${esc(a)}</p>`).join("")}</div></div>`
      : "";
  }

  function mostrarVisao(v) {
    estado.view = v;
    document.querySelectorAll("#sec-previsao [data-pvview]").forEach((b) => b.classList.toggle("active", b.dataset.pvview === v));
    ["lista", "turmas", "fora", "geo"].forEach((n) => { $(`pv-view-${n}`).style.display = n === v ? "" : "none"; });
    if (!estado.dados) return;
    if (v === "lista") desenharLinhas();
    else if (v === "turmas") desenharTurmas();
    else if (v === "geo") desenharGeo();
    else desenharFora();
  }

  function ligar() {
    if (ligada) return;
    ligada = true;
    document.querySelectorAll("#sec-previsao [data-pvview]").forEach((b) => b.addEventListener("click", () => mostrarVisao(b.dataset.pvview)));
    document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((b) => b.addEventListener("click", () => {
      estado.aba = b.dataset.pvtab;
      document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((x) => x.classList.toggle("active", x === b));
      desenharLinhas();
    }));
    $("pv-busca").addEventListener("input", (e) => { estado.busca = e.target.value; desenharLinhas(); });
    $("pv-turma").addEventListener("change", (e) => { estado.turma = e.target.value; desenharLinhas(); });
    $("pv-agrupar").addEventListener("change", (e) => { estado.agrupar = e.target.checked; desenharLinhas(); });
    $("pv-fora-busca").addEventListener("input", (e) => { estado.foraBusca = e.target.value; desenharFora(); });
    $("pv-fora-turma").addEventListener("change", (e) => { estado.foraTurma = e.target.value; desenharFora(); });
    $("pv-geo-busca").addEventListener("input", (e) => { estado.geoBusca = e.target.value; desenharGeo(); });
    $("pv-geo-turma").addEventListener("change", (e) => { estado.geoTurma = e.target.value; desenharGeo(); });
    $("pv-exportar").addEventListener("click", () => { if (estado.dados) exportar(); });
  }

  async function carregarPrevisao() {
    ligar();
    try {
      estado.dados = await apiGet("/previsao");
    } catch (e) {
      estado.dados = { linhas: [], cartoes: [], avisos: [], turmas: [], fora: null, ano: "" };
      $("pv-cartoes").innerHTML = "";
      $("pv-avisos").innerHTML = "";
      $("pv-cnt").textContent = "0";
      $("pv-tbody").innerHTML = "";
      $("pv-vazio-msg").textContent = "Não foi possível carregar /previsao.";
      $("pv-vazio").style.display = "";
      console.warn("Previsão: erro ao carregar", e);
      return;
    }
    try { estado.geo = await apiGet("/direcionados-geo"); } catch (e) { estado.geo = null; console.warn("Direcionados GEO: erro ao carregar", e); }
    const d = estado.dados;
    $("pv-ano").textContent = d.ano;
    const titulo = $("topbar-title");
    if (titulo && $("sec-previsao").classList.contains("active")) titulo.textContent = `Previsão ${d.ano}`;
    const c = d.contagem || {};
    const rotulos = { todos: `Todos (${c.total || 0})`, rematriculado: `Rematriculados (${c.rematriculados || 0})`, novo: `Novos (${c.novos || 0})` };
    document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((b) => { b.textContent = rotulos[b.dataset.pvtab]; });
    preencherFiltroTurma("pv-turma", (d.turmas || []).map((t) => t.turma), estado.turma, "Todas as turmas");
    desenharCartoes(d);
    desenharAvisos(d);
    mostrarVisao(estado.view);
    $("pv-fora-n").textContent = d.fora && d.fora.disponivel ? `(${d.fora.contagem.total})` : "";
  }

  window.carregarPrevisao = carregarPrevisao;
})();
