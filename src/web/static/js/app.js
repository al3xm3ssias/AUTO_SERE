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
    { tipo: "pasta", label: "Pasta a ser analisada" },
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
    { tipo: "pasta", label: "Pasta raiz dos alunos" },
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
        <div class="folder-picker" id="btn-escolher-pasta" data-titulo="${campo.label || "Selecione a pasta"}">
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

  document.getElementById("btn-voltar-automacoes").addEventListener("click", () => {
    document.getElementById("automacoes-lista").style.display = "block";
    document.getElementById("automacoes-execucao").style.display = "none";
    document.getElementById("topbar-title").textContent = "Automações";
  });

  document.getElementById("btn-executar-tarefa").addEventListener("click", async () => {
    const btn = document.getElementById("btn-executar-tarefa");
    const original = btn.innerHTML;
    btn.innerHTML = `<span class="spin">${icon("loader")}</span> Executando...`;
    btn.disabled = true;

    const payload = { automacao: automacaoAtual };

    const switchTurma = document.getElementById("switch-por-turma");
    if (switchTurma) {
      payload.por_turma = switchTurma.classList.contains("on");
      payload.turmas = Array.from(
        document.querySelectorAll("#checklist-turmas input:checked")
      ).map((el) => el.value);
    }

    const campoPasta = document.getElementById("pasta-selecionada");
    if (campoPasta) {
      payload.pasta = campoPasta.textContent;
    }

    // Coleta qualquer outro campo dinâmico (texto/select) pelo id
    document.querySelectorAll("#campos-automacao input[type=text], #campos-automacao select").forEach((el) => {
      if (el.id && el.id !== "select-turmas") payload[el.id] = el.value;
    });

    try {
      await apiPost(`/automacoes/${automacaoAtual}/executar`, payload);
      toast("Tarefa executada com sucesso");
    } catch (e) {
      toast(`Endpoint /automacoes/${automacaoAtual}/executar ainda não conectado`);
    } finally {
      btn.innerHTML = original;
      btn.disabled = false;
    }
  });
}

/* ---------- Configurações ---------- */

const DETALHE_CONFIG = {
  senha_sere: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do SERE</h4>
    <div class="field"><label>Usuário</label><input type="text" id="cfg-sere-usuario" placeholder="usuário do SERE"></div>
    <div class="field"><label>Senha</label><input type="password" id="cfg-sere-senha" placeholder="••••••••"></div>
    <button class="btn-primary" id="cfg-sere-salvar">Salvar credenciais</button>`,
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
    });
  });
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

/* ---------- Wizard primeira execução ---------- */

const PASSOS_WIZARD = [
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

      if (chave === "credenciais_sere") {
        const login = window.prompt("Usuário (CPF) do SERE:");
        if (!login) return;
        const senha = window.prompt("Senha do SERE:");
        if (!senha) return;
        payload = { login, senha };
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
});