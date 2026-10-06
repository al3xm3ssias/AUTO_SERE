/* ============================================================
   AUTO SERE — app.js
   Navegação de telas, tema e chamadas à API Flask (/web/api/...)
   ============================================================ */

const API_BASE = "/web/api";

/* ---------- Utilidades ---------- */

function toast(msg) {
  const el = document.getElementById("toast");
  document.getElementById("toast-msg").textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2600);
}

async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`Erro ao buscar ${path}`);
  return res.json();
}

async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let dados = null;
  try {
    dados = await res.json();
  } catch (e) {
    // resposta sem corpo JSON (ex.: erro de rede/servidor fora do ar)
  }
  if (!res.ok) {
    const mensagem = (dados && (dados.erro || dados.mensagem)) || `Erro ao enviar para ${path}`;
    throw new Error(mensagem);
  }
  return dados;
}

/* ---------- Tema ---------- */

function aplicarTema(tema) {
  document.documentElement.setAttribute("data-theme", tema);
  localStorage.setItem("auto_sere_tema", tema);
  document.querySelectorAll(".theme-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === tema);
  });
}

function initTema() {
  const salvo = localStorage.getItem("auto_sere_tema") || "escuro";
  aplicarTema(salvo);
  document.getElementById("theme-switcher").addEventListener("click", (ev) => {
    const btn = ev.target.closest(".theme-btn");
    if (btn) aplicarTema(btn.dataset.theme);
  });
}

/* ---------- Footer fixo: preenche o ano atual dinamicamente ---------- */

function initFooter() {
  const anoAtual = new Date().getFullYear();
  const footerAno = document.getElementById("footer-ano");
  const sidebarAno = document.getElementById("sidebar-ano");
  if (footerAno) footerAno.textContent = anoAtual;
  if (sidebarAno) sidebarAno.textContent = anoAtual;
}

/* ---------- Sidebar: collapse (desktop) e overlay (mobile) ---------- */

function initSidebar() {
  const sidebar = document.getElementById("sidebar");
  const mainWrapper = document.getElementById("main-wrapper");
  const topbar = document.getElementById("topbar");
  const footer = document.getElementById("app-footer");
  const toggle = document.getElementById("sidebar-toggle");
  const overlay = document.getElementById("sidebar-overlay");

  toggle.addEventListener("click", () => {
    if (window.innerWidth <= 900) {
      sidebar.classList.toggle("mobile-open");
      overlay.classList.toggle("show");
    } else {
      sidebar.classList.toggle("collapsed");
      mainWrapper.classList.toggle("sidebar-collapsed");
      topbar.classList.toggle("sidebar-collapsed");
      footer.classList.toggle("sidebar-collapsed");
    }
  });

  overlay.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    overlay.classList.remove("show");
  });

  // Acordeon do grupo "Automações"
  const toggleAuto = document.getElementById("toggle-automacoes");
  const subAuto = document.getElementById("sub-automacoes");
  toggleAuto.addEventListener("click", () => {
    toggleAuto.classList.toggle("open");
    subAuto.classList.toggle("open");
  });
}

/* ---------- Navegação entre telas ---------- */

const TITULOS = {
  painel: "Painel principal",
  turmas: "Turmas",
  alunos: "Alunos",
  documentos: "Análise de documentos",
  prematricula: "Pré matrícula",
  funcionarios: "Funcionários",
  automacoes: "Automações",
  configuracoes: "Configurações",
  "primeira-execucao": "1ª execução do sistema",
  ajuda: "Ajuda",
};

function irPara(view, opts = {}) {
  document.querySelectorAll(".section").forEach((v) => v.classList.remove("active"));
  const alvo = document.getElementById(`sec-${view}`);
  if (alvo) alvo.classList.add("active");

  document.getElementById("topbar-title").textContent = TITULOS[view] || view;

  if (view === "turmas") {
    carregarTurmas();
  } else if (view === "alunos") {
    carregarAlunos();
  } else if (view === "documentos") {
    carregarDocumentos();
  } else if (view === "prematricula" || view === "funcionarios") {
    carregarTabelaGenerica(view);
  }
  if (view === "painel") {
    carregarPainel();
  }
  if (view === "automacoes" && !opts.manterExecucao) {
    document.getElementById("automacoes-lista").style.display = "block";
    document.getElementById("automacoes-execucao").style.display = "none";
  }
  if (view === "primeira-execucao") {
    carregarWizard();
  }

  // Fecha a sidebar no mobile ao navegar
  document.getElementById("sidebar").classList.remove("mobile-open");
  document.getElementById("sidebar-overlay").classList.remove("show");
}

function initNavegacao() {
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
      item.classList.add("active");

      irPara(item.dataset.view);

      // Itens de automação (data-auto) já abrem direto na tela de execução
      if (item.dataset.auto) {
        abrirAutomacao(item.dataset.auto, item.querySelector(".nav-item-label")?.textContent || item.textContent.trim());
      }
    });
  });

  document.querySelectorAll("[data-goto]").forEach((el) => {
    el.addEventListener("click", () => {
      irPara(el.dataset.goto);
      const navAlvo = document.querySelector(`.nav-item[data-view="${el.dataset.goto}"]`);
      if (navAlvo) {
        document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
        navAlvo.classList.add("active");
      }
    });
  });
}

/** Garante que o acordeon "Automações" esteja expandido (usado ao
 * navegar para uma automação por outro caminho que não o próprio clique
 * no acordeon, ex: card da lista de automações ou link "Ver tudo"). */
function abrirAcordeonAutomacoes() {
  document.getElementById("toggle-automacoes")?.classList.add("open");
  document.getElementById("sub-automacoes")?.classList.add("open");
}

/* ---------- Painel principal ---------- */

const ICONES_METRICA = {
  total_alunos: { icon: "users", cor: "cyan" },
  meninos: { icon: "man", cor: "blue" },
  meninas: { icon: "woman", cor: "rose" },
  fila_prematricula: { icon: "clipboard", cor: "amber" },
  turmas: { icon: "school", cor: "violet" },
  docs_pendentes: { icon: "alertFile", cor: "amber" },
  fora_do_raio: { icon: "mapPinOff", cor: "rose" },
  transferidos: { icon: "transfer", cor: "cyan" },
  encaminhamentos: { icon: "heart", cor: "lime" },
};

/** Monta um .stat-card no mesmo padrão visual do painel original. */
function metricCard(item) {
  const meta = ICONES_METRICA[item.chave] || { icon: "bolt", cor: "cyan" };
  return `
    <div class="stat-card">
      <div class="stat-card-icon">${icon(meta.icon)}</div>
      <div class="stat-lbl">${item.label}</div>
      <div class="stat-val v-${meta.cor}">${item.valor}</div>
      ${item.sub ? `<div class="stat-sub">${item.sub}</div>` : ""}
    </div>`;
}

async function carregarPainel() {
  try {
    const resumo = await apiGet("/painel/resumo");
    document.getElementById("ultima-atualizacao").textContent = resumo.atualizado_em || "—";

    const totalAlunos = resumo.principais?.find((m) => m.chave === "total_alunos")?.valor;
    const tMeta = document.getElementById("t-meta");
    if (tMeta) {
      tMeta.innerHTML = `${resumo.atualizado_em || "—"}<br>${totalAlunos ?? "—"} alunos`;
    }

    document.getElementById("metrics-principais").innerHTML =
      (resumo.principais || []).map(metricCard).join("");
    document.getElementById("metrics-secundarias").innerHTML =
      (resumo.secundarias || []).map(metricCard).join("");
  } catch (e) {
    console.warn("Painel: usando dados de exemplo (endpoint ainda não conectado)", e);
  }

  try {
    const fila = await apiGet("/prematricula/fila?limit=5");
    const tbody = document.getElementById("tbody-prematricula");
    tbody.innerHTML = (fila.itens || []).map((r, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${r.nome}</td>
        <td>${r.turma}</td>
        <td><span class="badge bg-amber">${r.posicao}º</span></td>
        <td>${r.telefone_responsavel}</td>
        <td><a href="#" class="link-action" data-mensagem="${r.id}">Mandar mensagem</a></td>
      </tr>`).join("") || `<tr><td colspan="6" style="text-align:center; color:var(--txt3); padding:20px;">Nenhum registro na fila.</td></tr>`;
  } catch (e) {
    console.warn("Fila pré-matrícula: endpoint ainda não conectado", e);
  }
}

function anexarAcoesLinha(row, colunas) {
  return `<td><div class="row-actions">
      <button class="row-action-btn" title="Visualizar">${icon("eye")}</button>
      <button class="row-action-btn" title="Editar">${icon("pencil")}</button>
    </div></td>`;
}

/* ---------- Tabelas genéricas (turmas / alunos / prematricula / funcionarios) ---------- */

async function carregarTabelaGenerica(entity) {
  const thead = document.getElementById(`thead-${entity}`);
  const tbody = document.getElementById(`tbody-${entity}`);
  const view = document.getElementById(`view-${entity}`);
  const totalLabel = view.querySelector(".js-total");

  try {
    const data = await apiGet(`/${entity}/lista`);
    const colunas = data.colunas || [];
    thead.innerHTML = colunas.map((c) => `<th>${c.label}</th>`).join("") + "<th>Ação</th>";

    tbody.innerHTML = (data.linhas || []).map((row) => {
      const tds = colunas.map((c) => `<td>${row[c.chave] ?? ""}</td>`).join("");
      return `<tr>${tds}${anexarAcoesLinha(row, colunas)}</tr>`;
    }).join("") || `<tr><td colspan="10" style="text-align:center; color:var(--txt3); padding:24px;">Nenhum registro encontrado.</td></tr>`;

    totalLabel.textContent = `${data.total ?? (data.linhas || []).length} registros`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--txt3); padding:24px;">Endpoint /${entity}/lista ainda não conectado.</td></tr>`;
    totalLabel.textContent = "—";
    console.warn(`Tabela ${entity}: endpoint ainda não conectado`, e);
  }
}

/* ---------- Turmas (cards expansíveis por turma) ---------- */

let _turmasCache = [];

function badge(texto, cls) {
  return `<span class="badge ${cls}">${texto}</span>`;
}

function renderCardsTurmas(turmas) {
  const container = document.getElementById("turmas-lista");
  if (!turmas.length) {
    container.innerHTML = `<div class="card"><div class="card-body" style="text-align:center; color:var(--txt3); padding:24px;">Nenhuma turma encontrada. Rode a automação "Turmas" (menu Automações) para coletar os dados do SERE.</div></div>`;
    return;
  }

  container.innerHTML = turmas.map((t) => {
    const campos = t.alunos.length ? Object.keys(t.alunos[0]) : [];
    const linhasAlunos = t.alunos.map((aluno) =>
      `<tr>${campos.map((campo) => `<td class="td-mono">${aluno[campo] ?? "—"}</td>`).join("")}</tr>`
    ).join("");

    return `
      <div class="turma-block">
        <div class="turma-hdr" onclick="this.classList.toggle('open'); this.nextElementSibling.classList.toggle('open')">
          <span class="turma-nm"><span data-icon="users" style="margin-right:6px"></span>${t.nome}</span>
          <div class="turma-badges">
            ${badge(t.matriculados + " matr.", "bg-cyan")}
            ${t.transf ? badge(t.transf + " transf.", "bg-rose") : ""}
            ${t.fem ? badge(t.fem + " F", "bg-violet") : ""}
            ${t.masc ? badge(t.masc + " M", "bg-blue") : ""}
          </div>
          <span class="chev"><span data-icon="chevronDown"></span></span>
        </div>
        <div class="turma-body">
          <div class="tbl-wrap" style="border:none; border-radius:0; max-height:380px; overflow-y:auto">
            <table>
              <thead><tr>${campos.map((c) => `<th>${c}</th>`).join("")}</tr></thead>
              <tbody>${linhasAlunos}</tbody>
            </table>
          </div>
        </div>
      </div>`;
  }).join("");

  aplicarIconesDOM(container);
}

async function carregarTurmas() {
  const resumo = document.getElementById("turmas-resumo");
  resumo.textContent = "Carregando…";

  try {
    const data = await apiGet("/turmas/lista");
    _turmasCache = data.turmas || [];
    resumo.textContent = `${data.total_turmas ?? _turmasCache.length} turmas · ${data.total_matriculados ?? 0} matriculados · ${data.total_transferidos ?? 0} transferidos`;
    renderCardsTurmas(_turmasCache);
  } catch (e) {
    resumo.textContent = "—";
    document.getElementById("turmas-lista").innerHTML =
      `<div class="card"><div class="card-body" style="text-align:center; color:var(--txt3); padding:24px;">Endpoint /turmas/lista ainda não conectado.</div></div>`;
    console.warn("Turmas: endpoint ainda não conectado", e);
    return;
  }

  const busca = document.getElementById("turmas-busca");
  busca.oninput = () => {
    const termo = busca.value.trim().toLowerCase();
    const filtradas = termo
      ? _turmasCache.filter((t) => t.nome.toLowerCase().includes(termo))
      : _turmasCache;
    renderCardsTurmas(filtradas);
  };
}

/* ---------- Alunos (tabela com detalhe expansível) ---------- */

const alunosState = { search: "", sort: { col: "nome", dir: 1 }, filter: "todos" };
let _alunosCache = [];
let _alunosCampos = [];

// Grupos de campos do cadastro completo (ver src.automacao.alunos.get_dados_aluno)
// — nomes de campo exatamente como o SERE devolve.
const AL_GROUPS = [
  { label: "Identificação", keys: ["Nome", "CGM", "RG", "CPF", "NIS Estudante", "Nacionalidade"] },
  { label: "Nascimento", keys: ["Data Nascimento", "Sexo", "Cor", "Estado Civil", "Município Nascimento", "UF Nascimento"] },
  { label: "Endereço", keys: ["Endereço", "Número", "Complemento", "Bairro", "CEP", "Cidade", "UF"] },
  { label: "Responsável", keys: ["Mãe", "Pai", "Responsável", "Parentesco", "CPF Responsável", "NIS Responsável", "Celular Aluno", "Celular Responsável", "Telefone Residencial", "Telefone Comercial", "Email Aluno", "Email Responsável"] },
  { label: "Escola", keys: ["Bolsa Família"] },
];
const AL_SKIP_MAIN = new Set(["Email Google"]);

function _getField(aluno, ...chaves) {
  for (const k of chaves) {
    const v = aluno[k];
    if (v !== undefined && v !== null && String(v).trim()) return String(v).trim();
  }
  return "—";
}
function _getSituacao(aluno) { return _getField(aluno, "_situacao"); }
function _getTurma(aluno) { return _getField(aluno, "_turma"); }

function _situacaoBadge(situacao) {
  const s = String(situacao || "").toLowerCase();
  if (s.includes("matriculado")) return badge("Matriculado", "bg-lime");
  if (s.includes("transf")) return badge("Transferido", "bg-rose");
  return badge(situacao || "—", "bg-muted");
}

function _buildDetailHTML(aluno) {
  const assigned = new Set();
  const turma = aluno._turma;
  const situacao = aluno._situacao;

  const gruposHtml = AL_GROUPS.map((grupo) => {
    const campos = _alunosCampos.filter((f) => grupo.keys.some((k) => f.toLowerCase() === k.toLowerCase()));
    const itens = campos.filter((f) => {
      const v = aluno[f];
      return v !== undefined && v !== null && String(v).trim() && String(v).trim() !== "—";
    });
    itens.forEach((f) => assigned.add(f));

    let extra = "";
    if (grupo.label === "Escola") {
      if (turma && turma !== "—") {
        extra += `<div class="al-field-group"><span class="al-field-lbl">Turma <span style="color:var(--cyan); font-size:.6rem">· turmas.json</span></span><span class="al-field-val">${turma}</span></div>`;
      }
      if (situacao && situacao !== "—") {
        const sitS = String(situacao).toLowerCase();
        const cor = sitS.includes("matriculado") ? "var(--lime)" : sitS.includes("transf") ? "var(--rose)" : "var(--txt2)";
        extra += `<div class="al-field-group"><span class="al-field-lbl">Situação <span style="color:var(--cyan); font-size:.6rem">· turmas.json</span></span><span class="al-field-val" style="color:${cor}; font-weight:700">${situacao}</span></div>`;
      }
    }
    if (!itens.length && !extra) return "";
    return `<div class="al-section-ttl">${grupo.label}</div>` +
      itens.map((f) => `<div class="al-field-group"><span class="al-field-lbl">${f}</span><span class="al-field-val">${aluno[f]}</span></div>`).join("") + extra;
  }).join("");

  const resto = _alunosCampos.filter((f) =>
    !assigned.has(f) && !AL_SKIP_MAIN.has(f) &&
    aluno[f] !== undefined && aluno[f] !== null && String(aluno[f]).trim() && String(aluno[f]).trim() !== "—"
  );
  const restoHtml = resto.length
    ? `<div class="al-section-ttl">Outros</div>` + resto.map((f) => `<div class="al-field-group"><span class="al-field-lbl">${f}</span><span class="al-field-val mono">${aluno[f]}</span></div>`).join("")
    : "";

  return gruposHtml + restoHtml;
}

function renderAlunosRows() {
  const q = alunosState.search.toLowerCase();

  let dados = _alunosCache.filter((a) => {
    const sit = _getSituacao(a).toLowerCase();
    if (alunosState.filter === "matriculado" && !sit.includes("matriculado")) return false;
    if (alunosState.filter === "transferido" && !sit.includes("transf")) return false;
    if (!q) return true;
    return _alunosCampos.some((f) => String(a[f] || "").toLowerCase().includes(q)) ||
      _getTurma(a).toLowerCase().includes(q);
  });

  const { col, dir } = alunosState.sort;
  dados = dados.slice().sort((a, b) => {
    let va, vb;
    if (col === "nome") { va = _getField(a, "Nome"); vb = _getField(b, "Nome"); }
    else if (col === "cgm") { va = _getField(a, "CGM"); vb = _getField(b, "CGM"); }
    else if (col === "turma") { va = _getTurma(a); vb = _getTurma(b); }
    else { va = _getSituacao(a); vb = _getSituacao(b); }
    return va.localeCompare(vb) * dir;
  });

  const tbody = document.getElementById("alunos-tbody");
  const vazio = document.getElementById("alunos-empty");
  document.getElementById("alunos-cnt").textContent = `${dados.length} / ${_alunosCache.length}`;

  if (!dados.length) {
    tbody.innerHTML = "";
    vazio.style.display = "";
    return;
  }
  vazio.style.display = "none";

  tbody.innerHTML = dados.map((a, idx) => {
    const nome = _getField(a, "Nome");
    const cgm = _getField(a, "CGM");
    const turma = _getTurma(a);
    const situacao = _getSituacao(a);
    const rowId = `al-row-${idx}`;
    return `<tr class="al-main-row" data-row="${rowId}">
      <td style="width:36px; text-align:center; vertical-align:middle">
        <button class="al-expand-btn" data-btn="${rowId}" title="Ver detalhes">+</button>
      </td>
      <td class="td-name">${nome}</td>
      <td class="td-mono">${cgm}</td>
      <td class="td-mono">${turma}</td>
      <td>${_situacaoBadge(situacao)}</td>
    </tr>
    <tr class="al-detail-row" id="${rowId}">
      <td colspan="5"><div class="al-detail-inner">${_buildDetailHTML(a)}</div></td>
    </tr>`;
  }).join("");

  tbody.querySelectorAll(".al-expand-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rowId = btn.dataset.btn;
      const detailRow = document.getElementById(rowId);
      const aberto = detailRow.classList.toggle("open");
      btn.classList.toggle("open", aberto);
      btn.title = aberto ? "Fechar detalhes" : "Ver detalhes";
    });
  });
}

async function carregarAlunos() {
  const cnt = document.getElementById("alunos-cnt");
  cnt.textContent = "Carregando…";

  try {
    const data = await apiGet("/alunos/lista");
    _alunosCache = data.alunos || [];
    _alunosCampos = data.campos || [];
  } catch (e) {
    cnt.textContent = "—";
    document.getElementById("alunos-tbody").innerHTML =
      `<tr><td colspan="5" style="text-align:center; color:var(--txt3); padding:24px;">Endpoint /alunos/lista ainda não conectado.</td></tr>`;
    console.warn("Alunos: endpoint ainda não conectado", e);
    return;
  }

  document.querySelectorAll("#sec-alunos [data-af]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#sec-alunos [data-af]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      alunosState.filter = btn.dataset.af;
      renderAlunosRows();
    });
  });

  document.querySelectorAll("#sec-alunos thead th[data-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      if (alunosState.sort.col === th.dataset.sort) alunosState.sort.dir *= -1;
      else { alunosState.sort.col = th.dataset.sort; alunosState.sort.dir = 1; }
      document.querySelectorAll("#sec-alunos thead th").forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(alunosState.sort.dir === 1 ? "sort-asc" : "sort-desc");
      renderAlunosRows();
    });
  });

  document.getElementById("alunos-q").addEventListener("input", (e) => {
    alunosState.search = e.target.value;
    renderAlunosRows();
  });

  renderAlunosRows();
}

/* ---------- Automações ---------- */

const ICONES_AUTOMACAO = {
  gerar_pastas: "folderPlus",
  analisa_pasta: "fileSearch",
  analisa_sere: "fileSearch",
  documentos: "files",
  cruzamento: "compare",
  cep: "mapPin",
  sus: "heart",
  transferidos: "transfer",
  parecer_fund: "certificate",
  parecer_rco: "certificate",
  comprimir: "zip",
  coleta_emails: "mail",
  agendador: "clock",
  backup: "database",
  avisos: "send",
  compara_anos: "scale",
  termos: "certificate",
  mapear_pastas: "map",
  mascara: "shieldLock",
  rematricula: "refresh",
};

/**
 * Define quais campos cada automação precisa no formulário de execução.
 * Tipos suportados: "turma" (toggle + checklist de turmas),
 * "pasta" (seletor de pasta real via input webkitdirectory),
 * "texto" (input livre), "select" (combo com opções fixas).
 *
 * Automações não listadas aqui caem no padrão DEFAULT (turma + pasta).
 * TODO: ajuste esses campos conforme os parâmetros reais de cada script
 * em src/automacao/*.py.
 */
const CAMPOS_AUTOMACAO = {
  gerar_pastas: [
    { tipo: "turma" },
    { tipo: "pasta", label: "Pasta raiz dos arquivos" },
  ],
  analisa_pasta: [
    { tipo: "pasta", label: "Pasta a ser analisada", destino: "digitalizacao" },
  ],
  analisa_sere: [
    { tipo: "turma" },
  ],
  documentos: [
    { tipo: "pasta", label: "Pasta dos documentos" },
  ],
  cruzamento: [
    { tipo: "pasta", label: "Pasta dos documentos a cruzar" },
  ],
  cep: [
    { tipo: "texto", id: "cep-valor", label: "CEP", placeholder: "Ex: 84010-000" },
  ],
  sus: [
    { tipo: "turma" },
  ],
  transferidos: [
    { tipo: "turma" },
    { tipo: "pasta", label: "Pasta para guias de transferência" },
  ],
  parecer_fund: [
    { tipo: "turma" },
    { tipo: "pasta", label: "Pasta de saída dos pareceres" },
  ],
  parecer_rco: [
    { tipo: "turma" },
    { tipo: "pasta", label: "Pasta de saída dos pareceres" },
  ],
  comprimir: [
    { tipo: "pasta", label: "Pasta a ser comprimida" },
  ],
  coleta_emails: [],
  agendador: [
    { tipo: "select", id: "frequencia", label: "Frequência", opcoes: [
      { valor: "diaria", texto: "Diária" },
      { valor: "semanal", texto: "Semanal" },
      { valor: "mensal", texto: "Mensal" },
    ] },
  ],
  backup: [
    { tipo: "pasta", label: "Pasta de destino do backup" },
  ],
  avisos: [
    { tipo: "turma" },
  ],
  compara_anos: [
    { tipo: "select", id: "ano-1", label: "Ano base", opcoes: [
      { valor: "2025", texto: "2025" },
      { valor: "2026", texto: "2026" },
    ] },
    { tipo: "select", id: "ano-2", label: "Ano comparado", opcoes: [
      { valor: "2025", texto: "2025" },
      { valor: "2026", texto: "2026" },
    ] },
  ],
  termos: [
    { tipo: "pasta", label: "Pasta de saída dos termos" },
  ],
  mapear_pastas: [
    { tipo: "pasta", label: "Pasta raiz dos alunos", destino: "digitalizacao" },
  ],
  mascara: [
    { tipo: "pasta", label: "Pasta com os dados a mascarar" },
  ],
  rematricula: [
    { tipo: "turma" },
  ],
};

const CAMPOS_PADRAO = [
  { tipo: "turma" },
  { tipo: "pasta", label: "Pasta raiz dos arquivos" },
];

async function carregarListaAutomacoes() {
  const container = document.getElementById("lista-automacoes");
  try {
    const data = await apiGet("/automacoes/lista");
    container.innerHTML = (data.itens || []).map((a) => `
      <div class="automation-row" data-auto="${a.chave}" data-nome="${a.nome}">
        <div class="ic">${icon(ICONES_AUTOMACAO[a.chave] || "bolt")}</div>
        <div class="txt">
          <div class="name">${a.nome}</div>
          <div class="desc">${a.descricao}</div>
        </div>
        <span class="chev">${icon("chevronRight")}</span>
      </div>`).join("");

    container.querySelectorAll(".automation-row").forEach((row) => {
      row.addEventListener("click", () => abrirAutomacao(row.dataset.auto, row.dataset.nome));
    });
  } catch (e) {
    container.innerHTML = `<p style="padding:16px; color:var(--txt3); font-size:13px;">Endpoint /automacoes/lista ainda não conectado.</p>`;
    console.warn("Lista de automações: endpoint ainda não conectado", e);
  }
}

let automacaoAtual = null;

function abrirAutomacao(chave, nome) {
  automacaoAtual = chave;
  document.getElementById("automacoes-lista").style.display = "none";
  document.getElementById("automacoes-execucao").style.display = "block";
  document.getElementById("topbar-title").textContent = nome || chave;
  renderizarCamposAutomacao(chave);
  abrirAcordeonAutomacoes();
  ligarControlesExecucao();
  _execResetar();
  carregarFlagsAutomacao(chave);
  sincronizarExecucao(chave);
}

/** Monta o HTML de um campo do formulário conforme seu tipo. */
function campoHTML(campo) {
  if (campo.tipo === "turma") {
    return `
      <div class="switch-row">
        <button class="switch" id="switch-por-turma"></button>
        <span id="switch-label">Executar por turma?</span>
      </div>
      <div class="field" id="campo-turmas" style="display:none;">
        <label>Turmas</label>
        <select id="select-turmas">
          <option value="">Selecione...</option>
        </select>
        <div class="checklist" style="margin-top:8px;" id="checklist-turmas">
          <!-- preenchido via JS -->
        </div>
      </div>`;
  }
  if (campo.tipo === "pasta") {
    return `
      <div class="field">
        <label>${campo.label || "Pasta"}</label>
        <div class="folder-picker" id="btn-escolher-pasta" data-titulo="${campo.label || "Selecione a pasta"}"${campo.destino ? ` data-destino="${campo.destino}"` : ""}>
          <span data-icon="folder"></span>
          Clique para escolher a pasta no explorador de arquivos
          <div class="path" id="pasta-selecionada">Nenhuma pasta selecionada</div>
        </div>
      </div>`;
  }
  if (campo.tipo === "texto") {
    return `
      <div class="field">
        <label>${campo.label}</label>
        <input type="text" id="${campo.id}" placeholder="${campo.placeholder || ""}">
      </div>`;
  }
  if (campo.tipo === "select") {
    return `
      <div class="field">
        <label>${campo.label}</label>
        <select id="${campo.id}">
          <option value="">Selecione...</option>
          ${(campo.opcoes || []).map((o) => `<option value="${o.valor}">${o.texto}</option>`).join("")}
        </select>
      </div>`;
  }
  return "";
}

function renderizarCamposAutomacao(chave) {
  const campos = CAMPOS_AUTOMACAO[chave] ?? CAMPOS_PADRAO;
  const container = document.getElementById("campos-automacao");

  if (campos.length === 0) {
    container.innerHTML = `<p style="color:var(--txt3); font-size:13px; margin-bottom:16px;">Esta automação não precisa de parâmetros adicionais — clique em Executar tarefa para rodá-la.</p>`;
    return;
  }

  container.innerHTML = campos.map(campoHTML).join("");

  // Religa os handlers dos campos que acabaram de ser inseridos no DOM
  const switchTurma = document.getElementById("switch-por-turma");
  if (switchTurma) {
    switchTurma.addEventListener("click", () => {
      switchTurma.classList.toggle("on");
      document.getElementById("campo-turmas").style.display =
        switchTurma.classList.contains("on") ? "block" : "none";
    });
    carregarTurmasParaSelect();
  }

  const btnPasta = document.getElementById("btn-escolher-pasta");
  if (btnPasta) {
    btnPasta.addEventListener("click", () => abrirSeletorDePasta(btnPasta));
  }
}

/**
 * Chama o backend (/sistema/escolher-pasta), que abre a janela nativa
 * do Windows (tkinter) e devolve o caminho absoluto escolhido.
 */
async function abrirSeletorDePasta(btnPasta) {
  const campoPath = document.getElementById("pasta-selecionada");
  const original = btnPasta.innerHTML;
  btnPasta.innerHTML = `<span class="spin">${icon("loader")}</span> Abrindo explorador de arquivos...`;

  try {
    const data = await apiPost("/sistema/escolher-pasta", {
      titulo: btnPasta.dataset.titulo || "Selecione a pasta",
      destino: btnPasta.dataset.destino || undefined,  // "digitalizacao" => grava em config_usuario.json
    });

    if (data.erro) {
      toast(data.erro);
    } else if (data.cancelado || !data.caminho) {
      // usuário fechou o diálogo sem escolher nada — não altera o campo
    } else {
      campoPath.textContent = data.caminho;
      toast("Pasta selecionada");
    }
  } catch (e) {
    toast("Endpoint /sistema/escolher-pasta ainda não conectado");
  } finally {
    btnPasta.innerHTML = original;
    aplicarIconesDOM(btnPasta);
  }
}

async function carregarTurmasParaSelect() {
  const select = document.getElementById("select-turmas");
  const checklist = document.getElementById("checklist-turmas");
  if (!select || !checklist) return;
  try {
    const data = await apiGet("/turmas/lista");
    const linhas = data.linhas || [];
    select.innerHTML = `<option value="">Selecione...</option>` +
      linhas.map((t) => `<option value="${t.id}">${t.nome}</option>`).join("");
    checklist.innerHTML = linhas.map((t) => `
      <label class="checklist-item">
        <input type="checkbox" value="${t.id}"> ${icon("folder")} ${t.nome}
      </label>`).join("");
  } catch (e) {
    select.innerHTML = `<option value="">Endpoint /turmas/lista não conectado</option>`;
    checklist.innerHTML = "";
  }
}

function initAutomacoes() {
  carregarListaAutomacoes();
}


/* ---------- Execução de automações: executar / cancelar / acompanhar ---------- */
/* O botão "Executar tarefa" vira "Cancelar execução" enquanto a automação roda
   (acompanhada por polling em /automacoes/<chave>/status) e volta ao normal
   quando ela termina, é cancelada ou falha. Os handlers usam `onclick`, e não
   addEventListener: antes cada abertura de automação empilhava mais um listener
   no mesmo botão e um clique disparava várias execuções. */

let _execTimer = null;

const _execBotao = () => document.getElementById("btn-executar-tarefa");

function _execEstadoBotao(estado) {
  const btn = _execBotao();
  if (!btn) return;
  if (btn.dataset.rotuloOriginal === undefined) btn.dataset.rotuloOriginal = btn.innerHTML;
  btn.dataset.estado = estado;
  if (estado === "executando") {
    btn.disabled = false;
    btn.style.background = "var(--rose)";
    btn.style.borderColor = "var(--rose)";
    btn.style.color = "#fff";
    btn.innerHTML = `<span class="spin">${icon("loader")}</span> Cancelar execução`;
  } else if (estado === "cancelando") {
    btn.disabled = true;
    btn.style.background = "var(--rose)";
    btn.style.borderColor = "var(--rose)";
    btn.style.color = "#fff";
    btn.innerHTML = `<span class="spin">${icon("loader")}</span> Cancelando…`;
  } else {
    btn.disabled = false;
    btn.style.background = "";
    btn.style.borderColor = "";
    btn.style.color = "";
    btn.innerHTML = btn.dataset.rotuloOriginal;
  }
}

function _execLogBox(criar) {
  let box = document.getElementById("exec-log");
  const btn = _execBotao();
  if (!box && criar && btn) {
    box = document.createElement("pre");
    box.id = "exec-log";
    box.style.cssText =
      "margin-top:14px;max-height:240px;overflow:auto;padding:12px 14px;" +
      "background:var(--surface2,#0d1117);border:1px solid var(--border);border-radius:8px;" +
      "font-family:var(--mono);font-size:.7rem;line-height:1.5;color:var(--txt2);" +
      "white-space:pre-wrap;word-break:break-word;";
    (btn.closest(".form-card") || btn.parentElement).insertAdjacentElement("afterend", box);
  }
  return box;
}

function _execMostrarLogs(logs) {
  if (!logs || !logs.length) return;
  const box = _execLogBox(true);
  const noFim = box.scrollTop + box.clientHeight >= box.scrollHeight - 8;
  box.textContent = logs.slice(-60).join("\n");
  if (noFim) box.scrollTop = box.scrollHeight;
}

function _execParar() {
  if (_execTimer) clearInterval(_execTimer);
  _execTimer = null;
}

/** Zera o estado visual ao abrir outra automação (a anterior segue rodando no servidor). */
function _execResetar() {
  _execParar();
  document.getElementById("exec-log")?.remove();
  _execEstadoBotao("ocioso");
}

async function _execConsultar(chave, avisarAoTerminar) {
  let s;
  try {
    s = await apiGet(`/automacoes/${chave}/status`);
  } catch (e) {
    return;  // falha momentânea de rede: tenta de novo no próximo ciclo
  }
  if (chave !== automacaoAtual) { _execParar(); return; }  // usuário abriu outra automação
  _execMostrarLogs(s.logs);

  if (s.status === "executando") {
    _execEstadoBotao(s.cancelando ? "cancelando" : "executando");
    return;
  }
  _execParar();
  _execEstadoBotao("ocioso");
  if (!avisarAoTerminar) return;
  if (s.status === "concluido") toast("Automação concluída");
  else if (s.status === "cancelado") toast("Execução cancelada");
  else if (s.status === "erro") toast(`Erro: ${s.erro || "veja o registro abaixo"}`);
}

function _execAcompanhar(chave) {
  _execParar();
  _execTimer = setInterval(() => _execConsultar(chave, true), 2000);
  _execConsultar(chave, true);
}

/** Ao abrir uma automação já em execução, volta a mostrar "Cancelar" e retoma o acompanhamento. */
async function sincronizarExecucao(chave) {
  try {
    const s = await apiGet(`/automacoes/${chave}/status`);
    if (chave !== automacaoAtual) return;
    if (s.status === "executando") {
      _execMostrarLogs(s.logs);
      _execEstadoBotao(s.cancelando ? "cancelando" : "executando");
      _execAcompanhar(chave);
    }
  } catch (e) { /* sem status ainda: tela fica no estado normal */ }
}

function _execMontarPayload() {
  const payload = { automacao: automacaoAtual };

  const switchTurma = document.getElementById("switch-por-turma");
  if (switchTurma) {
    payload.por_turma = switchTurma.classList.contains("on");
    payload.turmas = Array.from(
      document.querySelectorAll("#checklist-turmas input:checked")
    ).map((el) => el.value);
  }

  const campoPasta = document.getElementById("pasta-selecionada");
  if (campoPasta) payload.pasta = campoPasta.textContent;

  // Qualquer outro campo dinâmico (texto/select) pelo id
  document.querySelectorAll("#campos-automacao input[type=text], #campos-automacao select").forEach((el) => {
    if (el.id && el.id !== "select-turmas") payload[el.id] = el.value;
  });
  return payload;
}

async function _execAoClicar() {
  const btn = _execBotao();
  const chave = automacaoAtual;
  if (!btn || !chave) return;

  // Já executando: o clique significa "cancelar".
  if (btn.dataset.estado === "executando") {
    _execEstadoBotao("cancelando");
    try {
      await apiPost(`/automacoes/${chave}/cancelar`, {});
      toast("Cancelamento solicitado…");
    } catch (e) {
      toast(e.message);
      _execEstadoBotao("executando");
    }
    return;
  }
  if (btn.dataset.estado === "cancelando") return;

  _execEstadoBotao("executando");
  document.getElementById("exec-log")?.remove();
  try {
    await apiPost(`/automacoes/${chave}/executar`, _execMontarPayload());
    toast("Automação iniciada");
    _execAcompanhar(chave);
  } catch (e) {
    _execEstadoBotao("ocioso");
    toast(e.message);
  }
}

function ligarControlesExecucao() {
  const voltar = document.getElementById("btn-voltar-automacoes");
  if (voltar) {
    voltar.onclick = () => {
      document.getElementById("automacoes-lista").style.display = "block";
      document.getElementById("automacoes-execucao").style.display = "none";
      document.getElementById("topbar-title").textContent = "Automações";
    };
  }
  const exec = _execBotao();
  if (exec) exec.onclick = _execAoClicar;
}

/* ---------- Flags (opções) de cada automação ---------- */
/* As flags vêm do próprio script (GET /automacoes/<chave>/flags) e cada
   alteração é salva na hora. O painel vai para o elemento #flags-automacao
   (aba "Configuração"); enquanto esse elemento não existir no template, aparece
   como um bloco recolhível "Opções do script" logo abaixo dos campos. */

function _flagsContainer() {
  const fixo = document.getElementById("flags-automacao");
  if (fixo) return fixo;
  let auto = document.getElementById("flags-automacao-auto");
  if (!auto) {
    const campos = document.getElementById("campos-automacao");
    if (!campos) return null;
    auto = document.createElement("details");
    auto.id = "flags-automacao-auto";
    auto.style.cssText = "margin:0 0 16px;padding:10px 14px;border:1px solid var(--border);border-radius:8px;";
    campos.insertAdjacentElement("afterend", auto);
  }
  return auto;
}

function _flagsLinha(f, tipo) {
  const aviso = f.aviso
    ? `<div style="color:var(--amber);font-size:.68rem;margin-top:2px;">⚠ ${_docEsc(f.aviso)}</div>` : "";
  const desc = f.descricao
    ? `<div style="color:var(--txt3);font-size:.7rem;margin-top:2px;">${_docEsc(f.descricao)}</div>` : "";
  return `
    <label style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;cursor:pointer;">
      <input type="${tipo}" ${tipo === "radio" ? 'name="flag-modo"' : ""} data-flag="${_docEsc(f.flag)}" ${f.ativa ? "checked" : ""} style="margin-top:3px;">
      <span>
        <span style="font-size:.84rem;">${_docEsc(f.rotulo)}</span>
        <code style="margin-left:6px;font-size:.66rem;color:var(--txt3);">${_docEsc(f.flag)}</code>
        ${desc}${aviso}
      </span>
    </label>`;
}

function _flagsResumo(flags) {
  const ativas = flags.filter((f) => f.ativa);
  return ativas.length
    ? `<span style="color:var(--amber)">${ativas.map((f) => _docEsc(f.rotulo)).join(" + ")}</span>`
    : `<span style="color:var(--txt3)">padrão (completo)</span>`;
}

async function carregarFlagsAutomacao(chave) {
  document.getElementById("flags-automacao-auto")?.remove();
  const fixo = document.getElementById("flags-automacao");
  if (fixo) fixo.innerHTML = "";

  let dados;
  try {
    dados = await apiGet(`/automacoes/${chave}/flags`);
  } catch (e) {
    return;
  }
  if (chave !== automacaoAtual) return;

  const cont = _flagsContainer();
  if (!cont) return;
  if (!dados.flags || !dados.flags.length) {
    if (cont.id === "flags-automacao") {
      cont.innerHTML = `<p style="color:var(--txt3);font-size:.82rem;">Esta automação não tem opções configuráveis.</p>`;
    } else {
      cont.remove();
    }
    return;
  }

  const modos = dados.flags.filter((f) => f.grupo === "modo");
  const outras = dados.flags.filter((f) => f.grupo !== "modo");
  const nenhumModo = !modos.some((f) => f.ativa);
  // O resumo na barra recolhida mostra o modo SALVO, para que uma opção
  // diferente do padrão nunca fique escondida.
  const titulo = cont.tagName === "DETAILS"
    ? `<summary style="cursor:pointer;font-size:.84rem;">Opções do script — <span class="flags-resumo">${_flagsResumo(dados.flags)}</span></summary>`
    : "";
  if (cont.tagName === "DETAILS" && dados.flags.some((f) => f.ativa)) cont.open = true;

  cont.innerHTML = `
    ${titulo}
    ${modos.length ? `
      <div style="margin-top:10px;font-family:var(--mono);font-size:.66rem;color:var(--txt3);letter-spacing:.08em;text-transform:uppercase;">Modo de execução</div>
      <label style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;cursor:pointer;">
        <input type="radio" name="flag-modo" data-flag="" ${nenhumModo ? "checked" : ""} style="margin-top:3px;">
        <span style="font-size:.84rem;">Completo (padrão)</span>
      </label>
      ${modos.map((f) => _flagsLinha(f, "radio")).join("")}` : ""}
    ${outras.length ? `
      <div style="margin-top:10px;font-family:var(--mono);font-size:.66rem;color:var(--txt3);letter-spacing:.08em;text-transform:uppercase;">Opções</div>
      ${outras.map((f) => _flagsLinha(f, "checkbox")).join("")}` : ""}
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:10px;">
      <button type="button" class="btn-sm" data-acao="salvar" disabled>Salvar opções</button>
      <button type="button" class="btn-sm" data-acao="padrao">Voltar ao padrão</button>
      <span class="flags-status" style="font-family:var(--mono);font-size:.68rem;color:var(--txt3);"></span>
    </div>`;

  const status = cont.querySelector(".flags-status");
  const btnSalvar = cont.querySelector('[data-acao="salvar"]');
  const btnPadrao = cont.querySelector('[data-acao="padrao"]');
  const marcadas = () => Array.from(cont.querySelectorAll("input[data-flag]:checked"))
    .map((i) => i.dataset.flag).filter(Boolean);

  // Nada é gravado ao marcar: só quando você clica em "Salvar opções".
  cont.querySelectorAll("input[type=radio],input[type=checkbox]").forEach((el) => {
    el.addEventListener("change", () => {
      btnSalvar.disabled = false;
      status.innerHTML = '<span style="color:var(--amber)">Alterações não salvas</span>';
    });
  });

  const gravar = async (flags) => {
    btnSalvar.disabled = btnPadrao.disabled = true;
    status.textContent = "Salvando…";
    try {
      await apiPost(`/automacoes/${chave}/flags`, { flags });
      await carregarFlagsAutomacao(chave);  // redesenha com o que ficou realmente salvo
      const novo = document.querySelector("#flags-automacao .flags-status, #flags-automacao-auto .flags-status");
      if (novo) novo.innerHTML = '<span style="color:var(--lime)">✓ Salvo — vale a partir da próxima execução</span>';
    } catch (e) {
      btnPadrao.disabled = false;
      status.innerHTML = `<span style="color:var(--rose)">✗ ${_docEsc(e.message)}</span>`;
    }
  };
  btnSalvar.addEventListener("click", () => gravar(marcadas()));
  btnPadrao.addEventListener("click", () => gravar([]));
}

/* ---------- Configurações ---------- */

const DETALHE_CONFIG = {
  senha_sere: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do SERE</h4>
    <div class="field"><label>Usuário</label><input type="text" id="cfg-sere-usuario" placeholder="usuário do SERE"></div>
    <div class="field"><label>Senha</label><input type="password" id="cfg-sere-senha" placeholder="••••••••"></div>
    <button class="btn-primary" id="cfg-sere-salvar">Salvar credenciais</button>`,
  escola: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Dados da escola</h4>
    <div id="cfg-escola-form"></div>`,
  pasta_digitalizacao: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Pasta de digitalização</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Pasta raiz onde ficam os documentos digitalizados dos alunos (as pastas das turmas). Por padrão é <code>dados/&lt;ano&gt;/DIGITALIZAÇÃO</code>.</p>
    <div class="field"><label>Caminho completo</label><input type="text" id="cfg-pasta-caminho" placeholder="/home/usuario/.../DIGITALIZAÇÃO"></div>
    <div id="cfg-pasta-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:6px;">Carregando…</div>
    <div id="cfg-pasta-padrao" style="font-family:var(--mono); font-size:.68rem; color:var(--txt3); margin-bottom:14px; word-break:break-all;"></div>
    <div style="display:flex; gap:10px; flex-wrap:wrap;">
      <button class="btn-primary" id="cfg-pasta-salvar">Salvar pasta</button>
      <button class="btn-sm" id="cfg-pasta-usar-padrao" style="padding:9px 16px;font-size:.78rem">Usar pasta padrão</button>
    </div>`,
  senha_rco: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do RCO</h4>
    <div class="field"><label>Usuário</label><input type="text" placeholder="usuário do RCO"></div>
    <div class="field"><label>Senha</label><input type="password" placeholder="••••••••"></div>
    <button class="btn-primary">Salvar credenciais</button>`,
  chave_gmail: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar chave do Gmail</h4>
    <div class="field"><label>Chave de API</label><input type="password" placeholder="chave de API do Gmail"></div>
    <button class="btn-primary">Salvar chave</button>`,
  outras_credenciais: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Outras credenciais</h4>
    <div class="field"><label>Serviço</label><input type="text" placeholder="nome do serviço"></div>
    <div class="field"><label>Token / chave</label><input type="password" placeholder="valor da credencial"></div>
    <button class="btn-primary">Adicionar</button>`,
  temas: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Tema do sistema</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Use o seletor no rodapé da barra lateral para trocar entre Escuro, Equilibrado e Claro.</p>`,
  perfil: `
    <div style="display:flex; align-items:center; gap:14px; margin-bottom:18px;">
      <div style="width:56px; height:56px; border-radius:50%; background:var(--badge-lime-bg); color:var(--lime); display:flex; align-items:center; justify-content:center;">
        ${icon("userCircle", "icon-xl")}
      </div>
      <div>
        <h4 style="margin-bottom:2px; font-size:.9rem;">Perfil</h4>
        <p style="font-size:.74rem; color:var(--txt3);">Dados do usuário e permissões</p>
      </div>
    </div>
    <div class="field"><label>Nome</label><input type="text" placeholder="Nome do usuário"></div>
    <div class="field">
      <label>Gênero</label>
      <select>
        <option value="">Não informado</option>
        <option value="feminino">Feminino</option>
        <option value="masculino">Masculino</option>
      </select>
    </div>
    <div class="field"><label>Cargo</label><input type="text" placeholder="Cargo / função"></div>
    <button class="btn-primary">Salvar perfil</button>`,
};

function initConfiguracoes() {
  document.querySelectorAll(".config-row[data-config]").forEach((row) => {
    row.addEventListener("click", () => {
      document.getElementById("config-detalhe").innerHTML =
        DETALHE_CONFIG[row.dataset.config] || "<p>Configuração não encontrada.</p>";
      aplicarIconesDOM(document.getElementById("config-detalhe"));
      if (row.dataset.config === "senha_sere") {
        conectarFormSenhaSere();
      }
      if (row.dataset.config === "pasta_digitalizacao") {
        conectarFormPastaDigitalizacao();
      }
      if (row.dataset.config === "escola") {
        montarFormEscola(document.getElementById("cfg-escola-form"), {});
      }
    });
  });
}

async function conectarFormPastaDigitalizacao() {
  const input = document.getElementById("cfg-pasta-caminho");
  const status = document.getElementById("cfg-pasta-status");
  const infoPadrao = document.getElementById("cfg-pasta-padrao");
  const btnSalvar = document.getElementById("cfg-pasta-salvar");
  const btnPadrao = document.getElementById("cfg-pasta-usar-padrao");
  if (!input || !status || !btnSalvar || !btnPadrao) return;

  const mostrar = (d) => {
    // Campo: pasta em uso; se nada em uso, sugere a padrão.
    input.value = d.caminho || d.padrao || "";
    if (d.configurada && d.usando_padrao) {
      status.innerHTML = '<span style="color:var(--lime)">✓ Usando a pasta padrão do ano</span>';
    } else if (d.configurada) {
      status.innerHTML = '<span style="color:var(--lime)">✓ Configurada (pasta personalizada)</span>';
    } else if (!d.usando_padrao && d.caminho) {
      status.innerHTML = '<span style="color:var(--rose)">✗ O caminho salvo não existe neste computador</span>';
    } else {
      status.innerHTML = '<span style="color:var(--amber)">Pendente — a pasta padrão ainda não existe</span>';
    }
    infoPadrao.textContent = "Padrão: " + d.padrao + (d.padrao_existe ? "" : " (ainda não existe)");
  };

  const enviar = async (corpo, botao, textoEspera) => {
    const original = botao.textContent;
    btnSalvar.disabled = btnPadrao.disabled = true;
    botao.textContent = textoEspera;
    try {
      const resp = await apiPost("/configuracoes/pasta-digitalizacao", corpo);
      mostrar(resp);
      toast(resp.mensagem || "Pasta salva");
    } catch (e) {
      toast(e.message);  // ex.: "A pasta não existe neste computador: ..."
    } finally {
      btnSalvar.disabled = btnPadrao.disabled = false;
      botao.textContent = original;
    }
  };

  try {
    mostrar(await apiGet("/configuracoes/pasta-digitalizacao"));
  } catch (e) {
    status.textContent = "Não foi possível ler a configuração atual.";
  }

  btnSalvar.addEventListener("click", () => {
    const caminho = input.value.trim();
    if (!caminho) { toast("Informe o caminho da pasta"); return; }
    enviar({ caminho }, btnSalvar, "Salvando...");
  });
  btnPadrao.addEventListener("click", () => enviar({ usar_padrao: true }, btnPadrao, "Aplicando..."));
}

function conectarFormSenhaSere() {
  const btn = document.getElementById("cfg-sere-salvar");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const login = document.getElementById("cfg-sere-usuario").value.trim();
    const senha = document.getElementById("cfg-sere-senha").value;
    if (!login || !senha) {
      toast("Preencha usuário e senha do SERE");
      return;
    }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Salvando...";
    try {
      const resposta = await apiPost("/wizard/credenciais_sere/executar", { login, senha });
      toast(resposta.mensagem || "Credenciais salvas");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
}

/* ---------- Modal genérico ---------- */

// Abre um modal; `montar(corpo, fechar)` preenche o conteúdo.
// Esc ou o botão Cancelar fecham. Clicar fora NÃO fecha (evita perder o que foi digitado).
function abrirModal(titulo, montar, aoFechar) {
  const fundo = document.createElement("div");
  fundo.className = "modal-overlay";
  const card = document.createElement("div");
  card.className = "modal-card";
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-modal", "true");
  const h = document.createElement("h3");
  h.textContent = titulo;
  const corpo = document.createElement("div");
  card.append(h, corpo);
  fundo.appendChild(card);

  const onEsc = (e) => { if (e.key === "Escape") fechar(); };
  const fechar = () => {
    document.removeEventListener("keydown", onEsc);
    fundo.remove();
    if (aoFechar) aoFechar();
  };
  document.addEventListener("keydown", onEsc);
  document.body.appendChild(fundo);
  montar(corpo, fechar);
  const primeiro = corpo.querySelector("input, select, textarea");
  if (primeiro) primeiro.focus();
  return fechar;
}

// Pede usuário e senha do SERE. Resolve {login, senha} ou null (cancelado).
function pedirCredenciaisSere() {
  return new Promise((resolve) => {
    abrirModal("Credenciais do SERE", (corpo, fechar) => {
      corpo.innerHTML = `
        <div class="field"><label>Usuário (CPF)</label><input type="text" id="mdl-sere-login" autocomplete="username"></div>
        <div class="field"><label>Senha</label><input type="password" id="mdl-sere-senha" autocomplete="current-password"></div>
        <div class="modal-acoes">
          <button class="btn-sm" id="mdl-cancelar" style="padding:9px 16px;font-size:.78rem">Cancelar</button>
          <button class="btn-primary" id="mdl-ok">Salvar</button>
        </div>`;
      const enviar = () => {
        const login = corpo.querySelector("#mdl-sere-login").value.trim();
        const senha = corpo.querySelector("#mdl-sere-senha").value;
        if (!login || !senha) { toast("Preencha usuário e senha do SERE"); return; }
        resolve({ login, senha });
        fechar();
      };
      corpo.querySelector("#mdl-ok").addEventListener("click", enviar);
      corpo.querySelector("#mdl-sere-senha").addEventListener("keydown", (e) => { if (e.key === "Enter") enviar(); });
      corpo.querySelector("#mdl-cancelar").addEventListener("click", fechar);
    }, () => resolve(null));   // resolve(null) é ignorado se já resolveu com os dados
  });
}

/* ---------- Dados da escola (wizard e Configurações usam o mesmo formulário) ---------- */

function abrirModalEscola(aoSalvar) {
  abrirModal("Dados da escola", (corpo, fechar) => {
    montarFormEscola(corpo, { aoSalvar: () => { fechar(); if (aoSalvar) aoSalvar(); }, aoCancelar: fechar });
  });
}

function mascararCep(valor) {
  const d = String(valor || "").replace(/\D/g, "").slice(0, 8);
  return d.length > 5 ? d.slice(0, 5) + "-" + d.slice(5) : d;
}

async function montarFormEscola(container, { aoSalvar, aoCancelar } = {}) {
  if (!container) return;
  container.innerHTML = `
    <div class="field"><label>Nome da escola *</label><input type="text" id="esc-nome" maxlength="150"></div>
    <div class="field"><label>Nome abreviado</label><input type="text" id="esc-nome_abreviado" maxlength="60"></div>
    <div class="field">
      <label>CEP *</label>
      <div class="cep-linha">
        <input type="text" id="esc-cep" inputmode="numeric" placeholder="00000-000" maxlength="9">
        <button class="btn-sm" id="esc-buscar-cep" type="button" style="padding:9px 16px;font-size:.78rem">Buscar endereço</button>
      </div>
      <div id="esc-cep-msg" class="cep-msg"></div>
    </div>
    <div class="form-linha">
      <div class="field" style="grid-column:span 2"><label>Endereço (rua/avenida) *</label><input type="text" id="esc-logradouro"></div>
      <div class="field"><label>Número</label><input type="text" id="esc-numero" maxlength="10"></div>
    </div>
    <div class="form-linha">
      <div class="field"><label>Bairro</label><input type="text" id="esc-bairro"></div>
      <div class="field"><label>Cidade</label><input type="text" id="esc-cidade"></div>
      <div class="field"><label>Estado (UF)</label><input type="text" id="esc-uf" maxlength="2" style="text-transform:uppercase"></div>
    </div>
    <details class="esc-opcional">
      <summary>Identificação (opcional)</summary>
      <div class="form-linha" style="margin-top:12px">
        <div class="field"><label>Código da escola</label><input type="text" id="esc-codigo"></div>
        <div class="field"><label>INEP</label><input type="text" id="esc-inep" inputmode="numeric" maxlength="8"></div>
      </div>
      <div class="form-linha">
        <div class="field"><label>Telefone</label><input type="text" id="esc-telefone" inputmode="tel"></div>
        <div class="field"><label>E-mail</label><input type="text" id="esc-email" inputmode="email"></div>
      </div>
      <div class="field"><label>Responsável</label><input type="text" id="esc-responsavel"></div>
    </details>
    <div id="esc-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin:6px 0 12px;">Carregando…</div>
    <div class="modal-acoes" style="justify-content:flex-start">
      <button class="btn-primary" id="esc-salvar">Salvar dados da escola</button>
      ${aoCancelar ? '<button class="btn-sm" id="esc-cancelar" style="padding:9px 16px;font-size:.78rem">Cancelar</button>' : ""}
    </div>`;

  const $ = (id) => container.querySelector("#esc-" + id);
  const CAMPOS = ["nome", "nome_abreviado", "cep", "logradouro", "numero", "bairro", "cidade", "uf",
                  "codigo", "inep", "telefone", "email", "responsavel"];
  const msgCep = $("cep-msg");

  const preencher = (d) => {
    CAMPOS.forEach((c) => { $(c).value = c === "cep" ? (d.cep_formatado || "") : (d[c] || ""); });
  };

  const buscarCep = async (sobrescrever) => {
    const digitos = $("cep").value.replace(/\D/g, "");
    if (digitos.length !== 8) { if (sobrescrever) msgCep.textContent = "Digite o CEP com 8 dígitos."; return; }
    msgCep.textContent = "Buscando…";
    try {
      const r = await apiGet("/cep/" + digitos);
      // Botão: substitui o endereço. Ao sair do campo: só completa o que estiver vazio.
      [["logradouro", r.logradouro], ["bairro", r.bairro], ["cidade", r.cidade], ["uf", r.uf]].forEach(([c, v]) => {
        if (v && (sobrescrever || !$(c).value.trim())) $(c).value = v;
      });
      msgCep.innerHTML = '<span style="color:var(--lime)">✓ Endereço preenchido — confira e informe o número.</span>';
    } catch (e) {
      msgCep.innerHTML = '<span style="color:var(--amber)"></span>';
      msgCep.firstChild.textContent = "Não foi possível buscar: preencha o endereço manualmente.";
    }
  };

  $("cep").addEventListener("input", () => { $("cep").value = mascararCep($("cep").value); });
  $("cep").addEventListener("blur", () => buscarCep(false));
  $("buscar-cep").addEventListener("click", () => buscarCep(true));
  if (aoCancelar) $("cancelar").addEventListener("click", aoCancelar);

  $("salvar").addEventListener("click", async () => {
    const corpo = {};
    CAMPOS.forEach((c) => { corpo[c] = $(c).value; });
    const btn = $("salvar");
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Salvando...";
    try {
      const r = await apiPost("/configuracoes/escola", corpo);
      toast(r.mensagem || "Dados da escola salvos");
      $("status").innerHTML = '<span style="color:var(--lime)">✓ Dados salvos</span>';
      if (aoSalvar) aoSalvar(r);
    } catch (e) {
      toast(e.message);   // ex.: "Informe o nome da escola.; CEP inválido: informe 8 dígitos."
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });

  try {
    const r = await apiGet("/configuracoes/escola");
    preencher(r.dados);
    $("status").innerHTML = r.configurada
      ? '<span style="color:var(--lime)">✓ Escola configurada</span>'
      : '<span style="color:var(--amber)">Pendente — preencha nome, CEP e endereço</span>';
  } catch (e) {
    $("status").textContent = "Não foi possível ler a configuração atual.";
  }
}

/* ---------- Wizard primeira execução ---------- */

const PASSOS_WIZARD = [
  { chave: "escola", nome: "Dados da escola (nome, CEP e endereço)", desc: "Informe a escola uma vez; todos os scripts passam a usar esses dados." },
  { chave: "credenciais_sere", nome: "Salvar credenciais do SERE (obrigatório)", desc: "O usuário deve salvar as credenciais do SERE para continuar." },
  { chave: "turmas", nome: "Executar Turmas (turmas.py)", desc: "Pega os alunos e turmas da escola." },
  { chave: "gerar_pastas", nome: "Executar Gerar Pastas (gerar_pastas.py)", desc: "Gera as pastas dos alunos automaticamente." },
  { chave: "funcionarios", nome: "Executar Funcionários / Servidores (servidores.py)", desc: "Pega os funcionários e servidores da escola." },
  { chave: "alunos", nome: "Executar Alunos (apenas alunos.py)", desc: "Pega os dados completos dos alunos." },
  { chave: "google_api", nome: "Chave de acesso do Google (Google API)", desc: "Necessário para scripts que usam Google Sheets ou e-mail." },
  { chave: "whatsapp", nome: "Conectar WhatsApp (mensagens_prematricula.py)", desc: "Conecta o WhatsApp para envio de mensagens." },
];

async function carregarWizard() {
  const container = document.getElementById("wizard-lista");
  let status = {};
  try {
    status = await apiGet("/wizard/status");
  } catch (e) {
    console.warn("Wizard: endpoint /wizard/status ainda não conectado", e);
  }

  container.innerHTML = PASSOS_WIZARD.map((p, i) => {
    const concluido = status[p.chave] === true;
    return `
      <div class="wizard-step ${concluido ? "done" : ""}">
        <div class="wizard-num">${concluido ? icon("check") : i + 1}</div>
        <div class="txt">
          <div class="name">${p.nome}</div>
          <div class="desc">${p.desc}</div>
        </div>
        <div class="status">
          ${concluido
            ? '<span class="badge bg-lime">Concluído</span>'
            : `<button class="btn-sm" data-wizard-run="${p.chave}">Executar</button>`}
        </div>
      </div>`;
  }).join("");

  container.querySelectorAll("[data-wizard-run]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const chave = btn.dataset.wizardRun;
      let payload = {};

      if (chave === "escola") {
        abrirModalEscola(() => carregarWizard());
        return;
      }

      if (chave === "credenciais_sere") {
        // Modal com campo de senha mascarado (window.prompt exibiria a senha em texto).
        const dados = await pedirCredenciaisSere();
        if (!dados) return;
        payload = dados;
      }

      const original = btn.textContent;
      btn.disabled = true;
      btn.textContent = "Executando...";
      try {
        const resposta = await apiPost(`/wizard/${chave}/executar`, payload);
        toast(resposta.mensagem || "Passo executado com sucesso");
        carregarWizard();
      } catch (e) {
        toast(e.message);
      } finally {
        btn.disabled = false;
        btn.textContent = original;
      }
    });
  });
}

/* ============================================================
   Análise de documentos — tela única com 3 abas internas
   (portado de renderDocsPC / renderDocsSistema / renderCruzamento
   do protótipo index.html). Cada aba é buscada sob demanda.
   ============================================================ */

const _DOC_ADDR_KW = [
  "residencia", "residência", "endereço", "endereco",
  "sanepar", "copel", "compesa", "conta de água", "conta de luz",
  "comprovante de end", "comprovante de resid",
];
const _DOC_SLOTS_IGNORADOS = new Set([
  "requerimento de matricula", "ficha de saude", "comprovante de trabalho",
  "guia de transferencia", "historico escolar do ensino medio",
  "historico escolar do ensino fundamental", "declaracao de matricula",
  "transferencia escolar", "parecer descritivo",
]);
const _DOC_SINONIMOS = {
  "requerimento de matricula": ["requerimento de matricula", "requerimento", "matricula"],
  "comprovante de residencia": ["comprovante de residencia", "residencia", "copel", "sanepar", "talao", "comprovante de endereco", "endereco"],
  "certidao de nascimento do aluno": ["certidao de nascimento", "certidao", "nascimento", "certidao de nascimento do aluno"],
  "cpf responsavel": ["cpf responsavel", "cpf do responsavel", "documento do responsavel", "rg e cpf do responsavel", "documentos dos responsaveis", "cpf pai", "cpf mae", "documento responsavel", "responsavel", "documentos", "documento"],
  "cpf do responsavel": ["cpf responsavel", "cpf do responsavel", "documento do responsavel", "rg e cpf do responsavel", "documentos dos responsaveis", "cpf pai", "cpf mae", "documento responsavel", "responsavel", "documentos", "documento"],
  "carteira de vacinacao": ["carteira de vacinacao", "carteirinha de vacinacao", "cartao de vacinacao", "carteirinha", "carteira"],
  "comprovante de vacinacao": ["carteira de vacinacao", "carteirinha de vacinacao", "cartao de vacinacao", "carteirinha", "carteira"],
  "declaracao de vacina": ["declaracao de vacina", "vacinacao", "vacina", "carteira de vacinacao", "carteirinha de vacinacao", "cartao de vacinacao", "carteirinha", "carteira"],
  "rg do aluno": ["rg do aluno", "rg aluno", "rg"],
  "cpf do aluno": ["cpf do aluno", "cpf aluno"],
};
const _DOC_PALAVRAS_IGNORADAS = new Set(["do", "de", "da", "das", "dos", "em", "com", "para", "por", "aluno", "uma", "num"]);
const _DOC_SINONIMO_MAP = new Map();
for (const [slot, termos] of Object.entries(_DOC_SINONIMOS)) {
  for (const t of termos) _DOC_SINONIMO_MAP.set(t, slot);
  _DOC_SINONIMO_MAP.set(slot, slot);
}

const _docNorm = (s) => String(s).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
const _docFileToText = (fn) =>
  _docNorm(String(fn || "").replace(/^\d+[-_]/, "").replace(/[-_]/g, " ").replace(/\.\w{2,4}$/, "").trim());
const _docIsAddr = (s) => _DOC_ADDR_KW.some((k) => String(s).toLowerCase().includes(k));

function _docMatchSlot(rawText) {
  const txt = _docNorm(rawText);
  if (_DOC_SINONIMO_MAP.has(txt)) return _DOC_SINONIMO_MAP.get(txt);
  for (const [termo, slot] of _DOC_SINONIMO_MAP) {
    if (txt.includes(termo)) return slot;
  }
  const tokens = txt.split(/\s+/).filter((t) => t && !_DOC_PALAVRAS_IGNORADAS.has(t));
  for (const [termo, slot] of _DOC_SINONIMO_MAP) {
    const tTokens = termo.split(/\s+/).filter((t) => t && !_DOC_PALAVRAS_IGNORADAS.has(t));
    if (tTokens.length > 0 && tTokens.every((t) => tokens.includes(t))) return slot;
  }
  return null;
}
const _docIsBasic = (rawText) => {
  const s = _docMatchSlot(rawText);
  return s !== null && !_DOC_SLOTS_IGNORADOS.has(s);
};

const _docEsc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function _docStat({ label, val, sub = "", cls = "v-cyan", ic = "" }) {
  return `<div class="stat-card">
    ${ic ? `<div class="stat-card-icon">${icon(ic)}</div>` : ""}
    <div class="stat-lbl">${label}</div>
    <div class="stat-val ${cls}">${val}</div>
    <div class="stat-sub">${sub}</div>
  </div>`;
}

function _docChips(docs, addrDocs = []) {
  if (!docs.length) return `<span style="font-family:var(--mono);font-size:.7rem;color:var(--txt3)">—</span>`;
  const as = new Set(addrDocs);
  return `<div class="chips">${docs.map((d) =>
    `<span class="chip${as.has(d) ? " addr" : ""}" title="${_docEsc(d)}">${_docEsc(d.replace(/_\d{8}_\d+/g, "").trim())}</span>`
  ).join("")}</div>`;
}

function _docVazio(colspan, mensagem) {
  return `<tr><td colspan="${colspan}" style="text-align:center;color:var(--txt3);padding:24px">${mensagem}</td></tr>`;
}

function _docSort(data, col, dir, getters, fallbackCol = "nome") {
  const get = getters[col] || getters[fallbackCol];
  return data.slice().sort((a, b) => {
    const va = get(a), vb = get(b);
    if (typeof va === "number" && typeof vb === "number") return (va - vb) * dir;
    return String(va).localeCompare(String(vb), "pt-BR") * dir;
  });
}

function _docBindSort(theadId, estado, render) {
  document.querySelectorAll(`#${theadId} th[data-sort]`).forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const col = th.dataset.sort;
      if (estado.sort.col === col) estado.sort.dir *= -1;
      else { estado.sort.col = col; estado.sort.dir = 1; }
      document.querySelectorAll(`#${theadId} th`).forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(estado.sort.dir === 1 ? "sort-asc" : "sort-desc");
      render();
    });
  });
}

function _docBindPills(seletor, atributo, estado, chave, render) {
  document.querySelectorAll(seletor).forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(seletor).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      estado[chave] = btn.dataset[atributo];
      render();
    });
  });
}

const _docsEstado = {
  abaAtiva: "pc",
  tabsLigadas: false,
  carregado: { pc: false, pive: false, analise: false },
  pc:      { dados: [], filter: "all", search: "", sort: { col: "nome", dir: 1 } },
  pive:    { dados: [], tab: "todos", search: "", sort: { col: "nome", dir: 1 } },
  analise: { dados: [], meta: {}, filter: "all", search: "", sort: { col: "nome", dir: 1 } },
};

const _DOC_ORIENTACAO = {
  pc: 'Rode a automação "Analisa documentos da pasta" (menu Automações) para gerar os dados.',
  pive: 'Rode a automação "Analisa documentos do SERE" (menu Automações) para gerar os dados.',
  analise: 'Rode a automação "Cruzamento de docs" (menu Automações) — ela precisa dos dois relatórios anteriores.',
};

function carregarDocumentos() {
  if (!_docsEstado.tabsLigadas) {
    document.querySelectorAll("#doc-tabs [data-doctab]").forEach((btn) => {
      btn.addEventListener("click", () => mostrarAbaDocumentos(btn.dataset.doctab));
    });
    _docsEstado.tabsLigadas = true;
  }
  mostrarAbaDocumentos(_docsEstado.abaAtiva);
}

async function mostrarAbaDocumentos(aba) {
  _docsEstado.abaAtiva = aba;
  document.querySelectorAll("#doc-tabs [data-doctab]").forEach((b) =>
    b.classList.toggle("active", b.dataset.doctab === aba));
  document.querySelectorAll("#sec-documentos .doc-panel").forEach((p) =>
    p.classList.toggle("active", p.id === `doc-panel-${aba}`));

  if (_docsEstado.carregado[aba]) return;  // cache: alternar abas não refaz a chamada

  const rota = { pc: "/documentos/digitalizados", pive: "/documentos/pive", analise: "/documentos/analise" }[aba];
  try {
    const resp = await apiGet(rota);
    if (!resp.gerado) {
      _docMostrarNaoGerado(aba);
      return;
    }
    if (aba === "pc") _docIniciarPC(resp);
    else if (aba === "pive") _docIniciarPIVE(resp);
    else _docIniciarAnalise(resp);
    _docsEstado.carregado[aba] = true;
  } catch (e) {
    console.warn(`Documentos (${aba}): endpoint não respondeu`, e);
    _docMostrarNaoGerado(aba, true);
  }
}

function _docMostrarNaoGerado(aba, erro = false) {
  const ids = { pc: ["dc-stats", "dc-tbody", 5], pive: ["dp-stats", "dp-tbody", 8], analise: ["da-stats", "da-tbody", 8] }[aba];
  document.getElementById(ids[0]).innerHTML = "";
  const msg = erro ? "Não foi possível carregar os dados desta aba." : `Ainda não há dados. ${_DOC_ORIENTACAO[aba]}`;
  document.getElementById(ids[1]).innerHTML = _docVazio(ids[2], msg);
}

/* ---------- Aba 1 · Documentos Digitalizados ---------- */

function _docIniciarPC(resp) {
  const st = _docsEstado.pc;
  st.dados = (resp.alunos || []).map((e) => {
    const allDocs = e.documentos || [];
    const addrDocs = allDocs.filter(_docIsAddr);
    return {
      cgm: e.cgm, nome: e.nome, turma: e.turma, allDocs, addrDocs,
      hasAddr: addrDocs.length > 0,
      hasDocs: allDocs.length > 0,
      hasBasicDocs: allDocs.some((d) => _docIsBasic(_docFileToText(d))),
    };
  });
  const total = st.dados.length;
  const comDocs = st.dados.filter((e) => e.hasDocs).length;
  const withAddr = st.dados.filter((e) => e.hasAddr).length;
  const noAddr = st.dados.filter((e) => !e.hasAddr && e.hasDocs).length;
  const noDocs = st.dados.filter((e) => !e.hasBasicDocs).length;

  document.getElementById("doc-cnt-pc").textContent = total;
  document.getElementById("dc-stats").innerHTML = [
    _docStat({ label: "Total alunos", val: total, sub: "com pasta digitalizada", cls: "v-cyan", ic: "users" }),
    _docStat({ label: "Com docs", val: comDocs, sub: "possuem algum documento", cls: "v-lime", ic: "folder" }),
    _docStat({ label: "Com comp. endereço", val: withAddr, sub: `${((withAddr / Math.max(total, 1)) * 100).toFixed(0)}% do total`, cls: "v-lime", ic: "mapPin" }),
    _docStat({ label: "Sem comp. endereço", val: noAddr, sub: "têm docs, mas sem endereço", cls: "v-amber", ic: "alertFile" }),
    _docStat({ label: "Sem docs básicos", val: noDocs, sub: "nenhum doc de matrícula", cls: "v-rose", ic: "alertFile" }),
  ].join("");

  const rotulos = { "all": "Todos", "has-addr": `Com comp. endereço (${withAddr})`, "no-addr": `Sem comp. (${noAddr})`, "no-docs": `Sem docs básicos (${noDocs})` };
  document.querySelectorAll("[data-dcf]").forEach((b) => { b.textContent = rotulos[b.dataset.dcf]; });

  _docBindPills("[data-dcf]", "dcf", st, "filter", _docRenderPC);
  _docBindSort("dc-thead", st, _docRenderPC);
  document.getElementById("dc-q").addEventListener("input", (e) => { st.search = e.target.value; _docRenderPC(); });
  _docRenderPC();
}

function _docRenderPC() {
  const st = _docsEstado.pc;
  const q = st.search.toLowerCase();
  let data = st.dados;
  if (st.filter === "has-addr") data = data.filter((e) => e.hasAddr);
  if (st.filter === "no-addr") data = data.filter((e) => !e.hasAddr && e.hasDocs);
  if (st.filter === "no-docs") data = data.filter((e) => !e.hasBasicDocs);
  if (q) data = data.filter((e) => e.nome.toLowerCase().includes(q) || e.cgm.includes(q) || e.allDocs.some((d) => d.toLowerCase().includes(q)));

  data = _docSort(data, st.sort.col, st.sort.dir, {
    nome: (e) => e.nome || "",
    turma: (e) => e.turma || "",
    qtd: (e) => e.allDocs.length,
    addr: (e) => (e.hasAddr ? 1 : 0),
  });

  document.getElementById("dc-cnt").textContent = `${data.length} de ${st.dados.length} alunos`;
  const tbody = document.getElementById("dc-tbody");
  const empty = document.getElementById("dc-empty");
  if (!data.length) { tbody.innerHTML = ""; empty.style.display = ""; return; }
  empty.style.display = "none";

  tbody.innerHTML = data.map((e) => {
    const ab = e.hasAddr ? badge(`${e.addrDocs.length} doc(s)`, "bg-lime")
      : e.hasDocs ? badge("Não encontrado", "bg-rose") : badge("Sem docs", "bg-muted");
    return `<tr>
      <td class="td-name">${_docEsc(e.nome)}<small>CGM: ${_docEsc(e.cgm || "—")}</small></td>
      <td class="td-mono">${_docEsc(e.turma)}</td>
      <td class="td-num v-cyan">${e.allDocs.length}</td>
      <td>${ab}</td>
      <td>${_docChips(e.allDocs, e.addrDocs)}</td>
    </tr>`;
  }).join("");
}

/* ---------- Aba 2 · Documentos do PIVE ---------- */

function _docIniciarPIVE(resp) {
  const st = _docsEstado.pive;
  st.dados = (resp.alunos || []).map((e) => {
    const dets = e.detalhes || [];
    const val = dets.filter((d) => d.validado).length;
    return {
      ...e,
      val,
      pend: dets.length - val,
      total: e.total || dets.length,
      tipos: [...new Set(dets.map((d) => d.tipo).filter(Boolean))],
      isTransferido: String(e.situacao || "").toLowerCase().includes("transf"),
      hasBasicDocs: dets.some((d) => _docIsBasic(d.tipo || "")),
    };
  });
  const d = st.dados;
  const totalDocs = d.reduce((s, e) => s + e.total, 0);
  const validados = d.reduce((s, e) => s + e.val, 0);
  const nTransf = d.filter((e) => e.isTransferido).length;
  const nMatric = d.length - nTransf;
  const comPend = d.filter((e) => e.pend > 0).length;
  const semBasico = d.filter((e) => !e.hasBasicDocs).length;

  document.getElementById("doc-cnt-pive").textContent = d.length;
  document.getElementById("dp-stats").innerHTML = [
    _docStat({ label: "Alunos com docs", val: d.length, sub: "no PIVE/SERE", cls: "v-cyan", ic: "users" }),
    _docStat({ label: "Matriculados", val: nMatric, sub: "situação atual", cls: "v-lime", ic: "student" }),
    _docStat({ label: "Transferidos", val: nTransf, sub: "situação atual", cls: "v-rose", ic: "transfer" }),
    _docStat({ label: "Total arquivos", val: totalDocs, sub: "somando todos", cls: "v-blue", ic: "files" }),
    _docStat({ label: "Validados", val: validados, sub: "marcados como válidos", cls: "v-lime", ic: "certificate" }),
    _docStat({ label: "Não validados", val: totalDocs - validados, sub: "aguardando", cls: "v-amber", ic: "clock" }),
    _docStat({ label: "Sem docs básicos", val: semBasico, sub: "nenhum doc de matrícula", cls: "v-rose", ic: "alertFile" }),
  ].join("");

  const contagens = { todos: d.length, matriculados: nMatric, transferidos: nTransf, pendentes: comPend };
  const rotulos = { todos: "Todos", matriculados: "Matriculados", transferidos: "Transferidos", pendentes: "Com pendentes" };
  document.querySelectorAll("[data-dptab]").forEach((b) => {
    b.textContent = `${rotulos[b.dataset.dptab]} (${contagens[b.dataset.dptab]})`;
  });

  _docBindPills("[data-dptab]", "dptab", st, "tab", _docRenderPIVE);
  _docBindSort("dp-thead", st, _docRenderPIVE);
  document.getElementById("dp-q").addEventListener("input", (e) => { st.search = e.target.value; _docRenderPIVE(); });
  _docRenderPIVE();
}

function _docRenderPIVE() {
  const st = _docsEstado.pive;
  const q = st.search.toLowerCase();
  let data = st.dados;
  if (st.tab === "matriculados") data = data.filter((e) => !e.isTransferido);
  if (st.tab === "transferidos") data = data.filter((e) => e.isTransferido);
  if (st.tab === "pendentes") data = data.filter((e) => e.pend > 0);
  if (q) data = data.filter((e) => e.nome.toLowerCase().includes(q) || e.cgm.includes(q) || e.tipos.some((t) => t.toLowerCase().includes(q)));

  data = _docSort(data, st.sort.col, st.sort.dir, {
    nome: (e) => e.nome || "", cgm: (e) => e.cgm || "", turma: (e) => e.turma || "",
    situacao: (e) => e.situacao || "", total: (e) => e.total, val: (e) => e.val, pend: (e) => e.pend,
  });

  document.getElementById("dp-cnt").textContent =
    data.length < st.dados.length ? `${data.length} de ${st.dados.length} alunos` : `${st.dados.length} alunos`;
  const tbody = document.getElementById("dp-tbody");
  const empty = document.getElementById("dp-empty");
  if (!data.length) { tbody.innerHTML = ""; empty.style.display = ""; return; }
  empty.style.display = "none";

  tbody.innerHTML = data.map((e) => {
    const chips = (e.detalhes || []).length
      ? e.detalhes.map((d) =>
          `<span class="chip ${d.validado ? "chip-val" : "chip-pend"}" title="${_docEsc(d.arquivo || d.tipo)}">${_docEsc(d.tipo)}</span>`).join("")
      : (e.tipos.map((t) => `<span class="chip">${_docEsc(t)}</span>`).join("") || "—");
    return `<tr>
      <td class="td-name">${_docEsc(e.nome)}</td>
      <td class="td-mono">${_docEsc(e.cgm || "—")}</td>
      <td class="td-mono">${_docEsc(e.turma)}</td>
      <td>${_situacaoBadge(e.situacao)}</td>
      <td class="td-num v-cyan">${e.total}</td>
      <td>${e.val > 0 ? badge(e.val, "bg-lime") : "—"}</td>
      <td>${e.pend > 0 ? badge(e.pend, "bg-amber") : "—"}</td>
      <td><div class="chips">${chips}</div></td>
    </tr>`;
  }).join("");
}

/* ---------- Aba 3 · Análise (cruzamento PC × SERE) ---------- */

const _DOC_STATUS_META = {
  "Completo — todos PC anexados": { cls: "bg-lime", short: "Completo" },
  "Parcial — parte anexada": { cls: "bg-amber", short: "Parcial" },
  "Pendente — nenhum PC anexado": { cls: "bg-rose", short: "Pendente" },
  "Sem pasta no PC": { cls: "bg-muted", short: "Sem PC" },
  "Sem registro no SERE": { cls: "bg-muted", short: "Sem SERE" },
  "Sem docs básicos no PC": { cls: "bg-violet", short: "Sem básicos" },
};
const _DOC_FILTRO_STATUS = {
  completo: "Completo — todos PC anexados",
  parcial: "Parcial — parte anexada",
  pendente: "Pendente — nenhum PC anexado",
  sem_pasta: "Sem pasta no PC",
  sem_sere: "Sem registro no SERE",
  sem_basic: "Sem docs básicos no PC",
};
const _DOC_BASIC_SLOTS = [
  "certidao de nascimento do aluno", "comprovante de residencia",
  "comprovante de vacinacao", "cpf do aluno", "cpf responsavel",
];
const _DOC_LABELS = {
  "certidao de nascimento do aluno": "Certidão de Nascimento do Aluno",
  "comprovante de residencia": "Comprovante de Residência",
  "comprovante de vacinacao": "Comprovante de Vacinação",
  "cpf do aluno": "CPF do Aluno",
  "cpf responsavel": "CPF Responsável",
  "rg do aluno": "RG do Aluno",
  "cpf do responsavel": "CPF do Responsável",
  "rg": "RG do Aluno",
};
const _docLabel = (tipo) => _DOC_LABELS[tipo] || tipo.replace(/\b\w/g, (c) => c.toUpperCase());

function _docIniciarAnalise(resp) {
  const st = _docsEstado.analise;
  st.dados = resp.alunos || [];
  st.meta = { total: resp.total, atualizado: resp.atualizado_em || "—", resumo: resp.resumo || {} };
  const r = st.meta.resumo;

  document.getElementById("doc-cnt-analise").textContent = st.meta.total;
  document.getElementById("da-stats").innerHTML = [
    _docStat({ label: "Total analisados", val: st.meta.total, sub: `atualizado ${_docEsc(st.meta.atualizado)}`, cls: "v-cyan", ic: "fileSearch" }),
    _docStat({ label: "✓ Completo", val: r.completo || 0, sub: "todos PC → SERE OK", cls: "v-lime", ic: "certificate" }),
    _docStat({ label: "~ Parcial", val: r.parcial || 0, sub: "faltam alguns no SERE", cls: "v-amber", ic: "alertFile" }),
    _docStat({ label: "✗ Pendente", val: r.pendente || 0, sub: "nenhum PC foi anexado", cls: "v-rose", ic: "alertFile" }),
    _docStat({ label: "Sem pasta PC", val: r.sem_pasta_pc || 0, sub: "só no SERE", cls: "v-muted", ic: "folder" }),
    _docStat({ label: "Sem docs básicos", val: r.sem_docs_basicos || 0, sub: "pasta vazia / sem docs", cls: "v-violet", ic: "files" }),
  ].join("");

  const rotulos = {
    all: `Todos (${st.meta.total})`, completo: `Completo (${r.completo || 0})`, parcial: `Parcial (${r.parcial || 0})`,
    pendente: `Pendente (${r.pendente || 0})`, sem_basic: `Sem básicos (${r.sem_docs_basicos || 0})`,
  };
  document.querySelectorAll("[data-daf]").forEach((b) => { b.textContent = rotulos[b.dataset.daf]; });

  _docBarrasPorTipo(st.dados);
  _docBindPills("[data-daf]", "daf", st, "filter", _docRenderAnalise);
  _docBindSort("da-thead", st, _docRenderAnalise);
  document.getElementById("da-q").addEventListener("input", (e) => { st.search = e.target.value; _docRenderAnalise(); });
  _docRenderAnalise();
}

/* Barras de progresso por tipo: quantos dos documentos que existem no PC
   já foram anexados no SERE (Resumo.slots_anexados / Resumo.slots_pc).
   Observação: o index.html dividia slots_sere por slots_pc, o que passa
   de 100% quando o SERE tem documento que não existe no PC, e usava as
   chaves 'rg' e 'Certidao de nascimento', que não existem no JSON (essas
   duas barras ficavam zeradas). Aqui usamos as chaves reais do JSON. */
function _docBarrasPorTipo(alunos) {
  const slotPC = {}, slotAnexado = {};
  for (const a of alunos) {
    const r = a.Resumo || {};
    for (const s of r.slots_pc || []) slotPC[s] = (slotPC[s] || 0) + 1;
    for (const s of r.slots_anexados || []) slotAnexado[s] = (slotAnexado[s] || 0) + 1;
  }
  const tipos = [..._DOC_BASIC_SLOTS, "rg do aluno"];
  document.getElementById("da-slot-bars").innerHTML = tipos.map((slot) => {
    const pc = slotPC[slot] || 0, anex = slotAnexado[slot] || 0;
    const pct = pc > 0 ? Math.round((anex / pc) * 100) : 0;
    const cor = pct >= 80 ? "var(--lime)" : pct >= 40 ? "var(--amber)" : "var(--rose)";
    return `<div class="progress-bar-row">
      <span class="progress-lbl">${_docLabel(slot)}</span>
      <div class="progress-track"><div class="progress-fill" style="width:${pct}%;background:${cor}"></div></div>
      <span class="progress-val">${anex} / ${pc} no PC <span style="color:${cor}">(${pct}%)</span></span>
    </div>`;
  }).join("");
}

function _docCartaoTipo(tipo, info) {
  if (!info) {
    return `<div class="cruz-doc-card" style="background:rgba(255,94,122,.05);border-color:rgba(255,94,122,.2)">
      <div class="cruz-doc-lbl">${_docLabel(tipo)}</div>
      <div class="cruz-doc-status"><div class="dot dot-miss"></div><span style="font-family:var(--mono);font-size:.68rem;color:var(--rose)">Não encontrado</span></div>
    </div>`;
  }
  const { no_pc: noPC, anexado } = info;
  const dot = anexado ? "dot-ok" : noPC ? "dot-pend" : "dot-miss";
  const txt = anexado ? "PC ✓  SERE ✓" : noPC ? "No PC, falta no SERE" : "Só no SERE";
  const bg = anexado ? "rgba(134,239,172,.05)" : noPC ? "rgba(255,179,64,.05)" : "rgba(77,159,255,.05)";
  const cor = anexado ? "var(--lime)" : noPC ? "var(--amber)" : "var(--blue)";
  const fn = (icone, d) => `<div class="cruz-doc-fname" title="${_docEsc(d)}">${icone} ${_docEsc(d)}</div>`;
  return `<div class="cruz-doc-card" style="background:${bg}">
    <div class="cruz-doc-lbl">${_docLabel(tipo)}</div>
    <div class="cruz-doc-status"><div class="dot ${dot}"></div><span style="font-family:var(--mono);font-size:.68rem;color:${cor}">${txt}</span></div>
    ${(info.docs_pc || []).map((d) => fn("📁", d)).join("")}${(info.docs_sere || []).map((d) => fn("🖥", d)).join("")}
  </div>`;
}

function _docRenderAnalise() {
  const st = _docsEstado.analise;
  const q = st.search.toLowerCase();
  let data = st.dados;
  if (st.filter !== "all") {
    const alvo = _DOC_FILTRO_STATUS[st.filter];
    if (alvo) data = data.filter((a) => a.Status === alvo);
  }
  if (q) data = data.filter((a) => (a.Nome || "").toLowerCase().includes(q) || String(a.CGM || "").includes(q) || (a.Turma || "").toLowerCase().includes(q));

  data = _docSort(data, st.sort.col, st.sort.dir, {
    nome: (a) => a.Nome || "", turma: (a) => a.Turma || "", status: (a) => a.Status || "",
    docs_pc: (a) => a.Resumo?.docs_pc_total || 0,
    docs_sere: (a) => a.Resumo?.docs_sere_total || 0,
    falta: (a) => a.Resumo?.slots_pc_nao_anexado?.length || 0,
  });

  document.getElementById("da-cnt").textContent = `${data.length} de ${st.dados.length} alunos`;
  const tbody = document.getElementById("da-tbody");
  const empty = document.getElementById("da-empty");
  if (!data.length) { tbody.innerHTML = ""; empty.style.display = ""; return; }
  empty.style.display = "none";

  const traco = `<span style="font-family:var(--mono);font-size:.68rem;color:var(--txt3)">—</span>`;
  const rows = [];
  for (const a of data) {
    const r = a.Resumo || {};
    const meta = _DOC_STATUS_META[a.Status] || { cls: "bg-muted", short: a.Status };
    const rowId = `cruz-det-${a.CGM}`;

    const conhecidos = new Set([...(r.slots_anexados || []), ...(r.slots_pc_nao_anexado || []), ...(r.slots_sere_sem_pc || [])]);
    const ausentes = _DOC_BASIC_SLOTS.filter((s) => !conhecidos.has(s));
    const chip = (cls, s, dica, pref = "") => `<span class="slot-chip ${cls}" title="${s} — ${dica}">${pref}${_docLabel(s)}</span>`;

    const pend = (r.slots_pc_nao_anexado || []).map((s) => chip("slot-pend", s, "no PC mas não no SERE")).join("");
    const anex = (r.slots_anexados || []).map((s) => chip("slot-ok", s, "PC ✓ SERE ✓")).join("");
    const soSere = (r.slots_sere_sem_pc || []).map((s) => chip("slot-sere", s, "no SERE mas não no PC")).join("");
    const aus = ausentes.map((s) => chip("slot-absent", s, "não encontrado no PC nem no SERE", "✕ ")).join("");

    rows.push(`<tr>
      <td class="td-name">${_docEsc(a.Nome)}<small>CGM: ${_docEsc(a.CGM)} · ${_docEsc(a.Turma || "—")}</small></td>
      <td class="td-mono">${_docEsc(a.Turma || "—")}</td>
      <td>${badge(_docEsc(meta.short), meta.cls)}</td>
      <td class="td-num v-blue">${r.docs_pc_total || 0}</td>
      <td class="td-num v-cyan">${r.docs_sere_total || 0}</td>
      <td><div class="slot-grid">${pend || traco}</div></td>
      <td><div class="slot-grid">${anex}${soSere}${aus}</div></td>
      <td><button class="cruz-expand-btn" onclick="toggleCruzDetail('${rowId}', this)">▾ ver</button></td>
    </tr>`);

    const docs = a.Documentos || {};
    const cartoes = a.Status === "Parcial — parte anexada"
      ? _DOC_BASIC_SLOTS.map((t) => _docCartaoTipo(t, docs[t])).join("")
      : Object.entries(docs).map(([t, info]) => _docCartaoTipo(t, info)).join("");
    rows.push(`<tr class="cruz-detail-row" id="${rowId}">
      <td colspan="8"><div class="cruz-detail-inner">${cartoes || `<span style="font-family:var(--mono);font-size:.68rem;color:var(--txt3)">Sem documentos mapeados.</span>`}</div></td>
    </tr>`);
  }
  tbody.innerHTML = rows.join("");
}

window.toggleCruzDetail = function (id, btn) {
  const row = document.getElementById(id);
  if (!row) return;
  row.classList.toggle("open");
  btn.textContent = row.classList.contains("open") ? "▴ fechar" : "▾ ver";
};

/* ---------- Assistente de 1ª execução ---------- */

// Se a escola ainda não foi configurada, abre sozinho o assistente (1ª execução).
// Só age se o usuário ainda estiver no painel, para não "puxar" quem já navegou.
async function abrirAssistenteSeNecessario() {
  try {
    const status = await apiGet("/wizard/status");
    const painelAtivo = document.getElementById("sec-painel")?.classList.contains("active");
    if (status.escola === false && painelAtivo) {
      document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
      document.querySelector('.nav-item[data-view="primeira-execucao"]')?.classList.add("active");
      irPara("primeira-execucao");
    }
  } catch (e) {
    // endpoint indisponível: continua no painel
  }
}

/* ---------- Init ---------- */

document.addEventListener("DOMContentLoaded", () => {
  iniciarObservadorIcones();
  initTema();
  initFooter();
  initSidebar();
  initNavegacao();
  initAutomacoes();
  initConfiguracoes();
  carregarPainel();
  abrirAssistenteSeNecessario();
});