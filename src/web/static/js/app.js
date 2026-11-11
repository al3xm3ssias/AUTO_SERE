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
  if (sidebarAno) sidebarAno.textContent = document.body.dataset.anoLetivo || anoAtual;
}

/* ---------- Ano letivo: selo no topo, faixa de aviso e tela de carregamento ---------- */

let _anoCtx = null;                     // último contexto lido de /ano-letivo/contexto
let _anoOverlayToken = 0;

function emConsulta() {
  return !!(_anoCtx && _anoCtx.somente_consulta) || document.body.classList.contains("modo-consulta");
}

/* Tela cheia que avisa o usuário (ex.: "ano letivo restaurado"). `fecharEm` > 0: fecha sozinha com barra de
   progresso; senão fica o botão. Devolve uma Promise que resolve quando fecha. */
let _anoOverlayFechar = null;

function fecharTelaAno() { if (_anoOverlayFechar) _anoOverlayFechar(); }

function mostrarTelaAno({ titulo = "", texto = "", carregando = true, fecharEm = 0, botao = "Entendi", semBotao = false } = {}) {
  const ov = document.getElementById("ano-overlay");
  if (!ov) return Promise.resolve();
  const spinner = document.getElementById("ano-overlay-spinner");
  const barra = document.getElementById("ano-overlay-barra");
  const btn = document.getElementById("ano-overlay-botao");
  document.getElementById("ano-overlay-titulo").textContent = titulo;
  document.getElementById("ano-overlay-texto").textContent = texto;
  const automatico = fecharEm > 0;
  spinner.hidden = !carregando;
  barra.hidden = !(carregando && automatico);
  barra.classList.remove("anda");
  barra.style.setProperty("--ano-dur", `${fecharEm}ms`);
  void barra.offsetWidth;                                  // reinicia a animação da barra
  if (!barra.hidden) barra.classList.add("anda");
  btn.textContent = botao;
  btn.hidden = semBotao || (carregando && automatico);
  ov.hidden = false;
  requestAnimationFrame(() => ov.classList.add("visivel"));
  const token = ++_anoOverlayToken;
  return new Promise((resolve) => {
    const fechar = () => {
      if (token !== _anoOverlayToken) { resolve(); return; }   // outra tela já tomou o lugar
      ov.classList.remove("visivel");
      setTimeout(() => { if (token === _anoOverlayToken) ov.hidden = true; }, 260);
      resolve();
    };
    btn.onclick = fechar;
    _anoOverlayFechar = fechar;
    if (automatico) setTimeout(fechar, fecharEm);
    if (!btn.hidden) btn.focus();
  });
}

/* Troca o ano letivo na hora (sem reiniciar): tela de carregamento enquanto o servidor recarrega os dados do ano;
   depois recarrega a página. Devolve a resposta quando NÃO houve troca (ano já em uso) e null se houve erro. */
async function trocarAnoLetivo(corpo, alvo) {
  mostrarTelaAno({ titulo: `Carregando o ano letivo ${alvo}…`, texto: "Trocando os dados em uso. Aguarde um instante.", carregando: true, semBotao: true });
  try {
    const r = await apiPost("/configuracoes/ano-letivo", corpo);
    if (!r.trocou) { fecharTelaAno(); return r; }
    try { sessionStorage.setItem(`ano-consulta-visto-${r.ativo}`, "1"); } catch (e) { /* sem sessionStorage */ }
    const consulta = !!r.somente_consulta;
    await mostrarTelaAno({
      titulo: consulta ? `Ano letivo ${r.ativo} restaurado` : `Ano letivo ${r.ativo} carregado`,
      texto: consulta ? "Carregando os dados… Você está no modo somente consulta: dá para ver tudo, mas nada pode ser alterado."
                      : "Carregando os dados do ano letivo…",
      carregando: true, fecharEm: 1700,
    });
    location.reload();
    return null;
  } catch (e) {
    fecharTelaAno();
    toast(e.message);
    return null;
  }
}

function aplicarContextoAno(c) {
  _anoCtx = c;
  const consulta = !!c.somente_consulta;
  document.body.classList.toggle("modo-consulta", consulta);
  document.body.dataset.anoLetivo = c.ativo;
  const badge = document.getElementById("ano-badge");
  if (badge) {
    badge.classList.toggle("consulta", consulta);
    badge.title = consulta ? "Somente consulta: este ano letivo não pode ser alterado." : "Ano letivo em uso";
    document.getElementById("ano-badge-texto").textContent = `Ano letivo ${c.ativo}${consulta ? " · somente consulta" : ""}`;
  }
  const sidebarAno = document.getElementById("sidebar-ano");
  if (sidebarAno) sidebarAno.textContent = c.ativo;

  const banner = document.getElementById("ano-banner");
  if (banner) {
    const linhas = [];
    if (consulta) {
      linhas.push(`<b>Somente consulta.</b> Você está visualizando o ano letivo <b>${escaparHtml(c.ativo)}</b>: dá para ver tudo, mas nada pode ser alterado.`);
    }
    if (c.pendente_reinicio) {
      linhas.push(`A configuração aponta para o ano letivo <b>${escaparHtml(c.proximo)}</b>, mas o programa está em <b>${escaparHtml(c.ativo)}</b>.`);
    }
    banner.classList.toggle("info", !consulta);
    banner.innerHTML = `<div class="ano-banner-texto">${linhas.join("<br>")}</div>`
      + (c.pendente_reinicio && !c.fixado_por_ambiente ? `<button class="btn-sm" id="ano-banner-aplicar" type="button">Aplicar agora</button>` : "")
      + (consulta ? `<button class="btn-sm" id="ano-banner-voltar" type="button">Voltar ao ano atual…</button>` : "");
    banner.hidden = !linhas.length;
    const aplicar = document.getElementById("ano-banner-aplicar");
    if (aplicar) aplicar.addEventListener("click", () => trocarAnoLetivo({ ano: c.proximo }, c.proximo));
    const voltar = document.getElementById("ano-banner-voltar");
    if (voltar) voltar.addEventListener("click", () => {
      document.querySelector('.nav-item[data-view="configuracoes"]')?.click();
      setTimeout(() => document.querySelector('.config-row[data-config="ano_letivo"]')?.click(), 150);
    });
  }
  const btnExec = document.getElementById("btn-executar-tarefa");
  if (btnExec) _execEstadoBotao(btnExec.dataset.estado || "pronto");
}

async function carregarContextoAno() {
  const c = await apiGet("/ano-letivo/contexto");
  aplicarContextoAno(c);
  return c;
}

/* Ao abrir o programa voltado a um ano anterior: avisa uma vez por sessão que o ano foi restaurado e que é só consulta. */
async function iniciarContextoAno() {
  let c;
  try { c = await carregarContextoAno(); } catch (e) { return; }
  if (!c.somente_consulta) return;
  const chave = `ano-consulta-visto-${c.ativo}`;
  let visto = false;
  try { visto = sessionStorage.getItem(chave) === "1"; sessionStorage.setItem(chave, "1"); } catch (e) { /* sem sessionStorage */ }
  if (!visto) {
    mostrarTelaAno({
      titulo: `Ano letivo ${c.ativo} restaurado`,
      texto: `Carregando os dados de ${c.ativo}… Você está no modo somente consulta: dá para ver tudo, mas nada pode ser alterado.`,
      carregando: true, fecharEm: 2800,
    });
  }
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

  // Subgrupos dentro de "Automações" (Transferidos, Pareceres, Documentos...)
  document.querySelectorAll(".nav-subgroup-toggle").forEach((t) => {
    t.addEventListener("click", () => alternarSubgrupo(t.dataset.subgroup));
  });
}

/** Abre/fecha um subgrupo de automações. Ao abrir, fecha os outros
 * para o menu não crescer demais. */
function alternarSubgrupo(chave, abrir) {
  const toggle = document.querySelector(`.nav-subgroup-toggle[data-subgroup="${chave}"]`);
  const itens = document.querySelector(`.nav-subgroup-items[data-subgroup-items="${chave}"]`);
  if (!toggle || !itens) return;
  const vaiAbrir = abrir === undefined ? !itens.classList.contains("open") : abrir;
  if (vaiAbrir) {
    document.querySelectorAll(".nav-subgroup-toggle.open").forEach((t) => t.classList.remove("open"));
    document.querySelectorAll(".nav-subgroup-items.open").forEach((i) => i.classList.remove("open"));
  }
  toggle.classList.toggle("open", vaiAbrir);
  itens.classList.toggle("open", vaiAbrir);
}

/** Abre o subgrupo que contém a automação indicada (data-auto). */
function abrirSubgrupoDaAutomacao(chaveAuto) {
  const item = document.querySelector(`.nav-subitem[data-auto="${chaveAuto}"]`);
  const grupo = item?.closest(".nav-subgroup-items");
  if (grupo) alternarSubgrupo(grupo.dataset.subgroupItems, true);
}

/* ---------- Navegação entre telas ---------- */

const TITULOS = {
  painel: "Painel principal",
  turmas: "Turmas",
  alunos: "Alunos",
  documentos: "Análise de documentos",
  prematricula: "Pré matrícula",
  transferidos: "Transferidos",
  funcionarios: "Funcionários",
  calendario: "Calendário letivo",
  "corte-etario": "Corte etário",
  planilhas: "Planilhas do Drive",
  encaminhamentos: "Encaminhamentos do SUS",
  "fora-do-raio": "Alunos fora do raio",
  automacoes: "Automações",
  whatsapp: "WhatsApp",
  configuracoes: "Configurações",
  "primeira-execucao": "1ª execução do sistema",
  ajuda: "Ajuda",
};

function irPara(view, opts = {}) {
  if (view !== "primeira-execucao") pararMonitorWizard();
  if (view !== "whatsapp" && window.pararWhatsapp) window.pararWhatsapp();
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
  } else if (view === "prematricula") {
    carregarPreMatricula();
  } else if (view === "funcionarios") {
    carregarFuncionarios();
  } else if (view === "transferidos") {
    carregarTransferidos();
  } else if (view === "fora-do-raio") {
    carregarForaDoRaio();
  } else if (view === "encaminhamentos") {
    carregarEncaminhamentos();
  } else if (VIEWS_TABELA.includes(view)) {
    carregarTabelaGenerica(view);
  } else if (view === "calendario") {
    // calendario.js expõe carregarCalendario(); antes ninguém a chamava e a tela abria em branco.
    if (window.carregarCalendario) window.carregarCalendario();
  } else if (view === "corte-etario") {
    // corte_etario.js expõe carregarCorteEtario(); sem esta chamada a tela abre sem a tabela.
    if (window.carregarCorteEtario) window.carregarCorteEtario();
  } else if (view === "planilhas") {
    // planilhas.js expõe carregarPlanilhas(); sem esta chamada a tela abre sem a lista.
    if (window.carregarPlanilhas) window.carregarPlanilhas();
  }
  if (view === "painel") {
    carregarPainel();
  }
  if (view === "whatsapp" && window.carregarWhatsapp) window.carregarWhatsapp();
  if (view === "automacoes" && !opts.manterExecucao) {
    document.getElementById("automacoes-lista").style.display = "block";
    document.getElementById("automacoes-execucao").style.display = "none";
  }
  if (view === "primeira-execucao") {
    carregarWizard();
    iniciarMonitorWizard();
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
    const tbody = document.getElementById("tbody-painel-prematricula");   // (id próprio: "tbody-prematricula" é da tela Pré-matrícula)
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

/* ---------- Tabelas genéricas (prematricula / funcionarios / encaminhamentos / fora-do-raio) ---------- */

const VIEWS_TABELA = [];   // todas as telas de dados têm carregador próprio; a tabela genérica fica de reserva
const _FILTRO_CUSTOM = {};   // entity -> () => linhas visíveis (telas que não usam a barra de filtros genérica)
const _tabelas = {};   // entity -> { colunas, linhas } (dados completos; o filtro é feito aqui, no navegador)

const MENSAGEM_VAZIA = {
  prematricula: "Nenhum registro. Execute a coleta da pré-matrícula (menu Automações).",
  funcionarios: 'Nenhum funcionário. Execute "Funcionários / Servidores" (1ª execução ou menu Automações).',
};

function escaparHtml(valor) {
  return String(valor ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function semAcento(texto) {
  return String(texto ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

/** Linhas que passam pelo seletor de turma e pelos campos de texto (filtro livre + busca). */
function linhasFiltradas(entity) {
  const dados = _tabelas[entity];
  if (!dados) return [];
  const sec = document.getElementById(`sec-${entity}`);
  const turma = sec.querySelector('.js-filtro[data-key="turma"]')?.value || "";
  const termos = [...sec.querySelectorAll('.js-filtro[data-key="texto"], .js-busca')]
    .map((i) => semAcento(i.value.trim()))
    .filter(Boolean);
  if (_FILTRO_CUSTOM[entity]) return _FILTRO_CUSTOM[entity]();   // telas com filtro próprio (Fora do raio)
  return dados.linhas.filter((row) => {
    if (turma && row.turma !== turma) return false;
    if (!termos.length) return true;
    const texto = semAcento(dados.colunas.map((c) => row[c.chave] ?? "").join(" "));
    return termos.every((t) => texto.includes(t));
  });
}

/* ---------- Cards de resumo, mapa e gráfico das telas Fora do raio / Encaminhamentos ---------- */

const _CORES_CARTAO = ["cyan", "blue", "amber", "rose", "violet", "lime", "muted"];
const _CORES_BARRA = ["var(--rose)", "var(--amber)", "var(--blue)", "var(--violet)", "var(--cyan)", "var(--lime)"];

/** Mesmo .stat-card do painel; o conteúdo vem pronto do servidor (campo "cartoes"). */
function cartaoResumo(c) {
  const cor = _CORES_CARTAO.includes(c.cor) ? c.cor : "cyan";
  return `<div class="stat-card">
    <div class="stat-card-icon">${icon(c.icone || "bolt")}</div>
    <div class="stat-lbl">${escaparHtml(c.label)}</div>
    <div class="stat-val v-${cor}">${escaparHtml(c.valor)}</div>
    ${c.sub ? `<div class="stat-sub">${escaparHtml(c.sub)}</div>` : ""}
  </div>`;
}

/** Distância em km com a barrinha proporcional ao aluno mais distante (mesmas faixas de cor do protótipo). */
function barraDistancia(km, max) {
  const n = Number(km) || 0;
  const topo = Number(max) || 1;
  const pct = Math.min(100, (n / topo) * 100).toFixed(1);
  const cor = n >= 7 ? "var(--rose)" : n >= 5 ? "var(--amber)" : "var(--blue)";
  return `<div class="dist-bar">
    <span class="td-num" style="color:${cor}; min-width:48px">${n.toFixed(2).replace(".", ",")} km</span>
    <div class="dist-track"><div class="dist-fill" style="width:${pct}%; background:${cor}"></div></div>
  </div>`;
}

/** Cards de resumo, mapa da escola e gráfico de barras (tudo opcional por tela). */
function desenharExtrasTabela(entity, data) {
  const sec = document.getElementById(`sec-${entity}`);

  const cartoes = sec.querySelector(`#cartoes-${entity}`);
  if (cartoes) cartoes.innerHTML = (data.cartoes || []).map(cartaoResumo).join("");

  const mapa = sec.querySelector(`#mapa-${entity}`);
  if (mapa) {
    const m = data.mapa;
    if (m) {
      const d = 0.075;      // ~8 km em volta da escola
      const bbox = [m.longitude - d, m.latitude - d, m.longitude + d, m.latitude + d].join("%2C");
      mapa.innerHTML = `<iframe title="Mapa da escola" loading="lazy" allowfullscreen
        src="https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${m.latitude}%2C${m.longitude}"></iframe>`;
      mapa.style.display = "";
    } else {
      mapa.innerHTML = "";
      mapa.style.display = "none";
    }
  }

  const grafico = sec.querySelector(`#grafico-${entity}`);
  if (grafico) {
    const itens = data.grafico?.itens || [];
    const topo = Math.max(1, ...itens.map((i) => i.valor));
    grafico.innerHTML = itens.length
      ? `<div class="chart-card"><div class="chart-ttl">${escaparHtml(data.grafico.titulo || "")}</div>${itens.map((i, n) =>
          `<div class="hbar"><span class="hbar-lbl" title="${escaparHtml(i.label)}">${escaparHtml(i.label)}</span>
            <div class="hbar-track"><div class="hbar-fill" style="width:${Math.max(1, (i.valor / topo) * 100).toFixed(0)}%; background:${_CORES_BARRA[n % _CORES_BARRA.length]}"></div></div>
            <span class="hbar-val">${i.valor}</span></div>`).join("")}</div>`
      : "";
    grafico.style.display = itens.length ? "" : "none";
  }
}

function desenharTabela(entity) {
  const dados = _tabelas[entity];
  const tbody = document.getElementById(`tbody-${entity}`);
  const totalLabel = document.getElementById(`view-${entity}`).querySelector(".js-total");
  const linhas = linhasFiltradas(entity);
  const n = dados.colunas.length || 1;
  if (!linhas.length) {
    const msg = dados.linhas.length ? "Nenhum registro com esses filtros." : (MENSAGEM_VAZIA[entity] || "Nenhum registro encontrado.");
    tbody.innerHTML = `<tr><td colspan="${n}" style="text-align:center; color:var(--txt3); padding:24px;">${escaparHtml(msg)}</td></tr>`;
  } else {
    tbody.innerHTML = linhas.map((row) =>
      `<tr>${dados.colunas.map((c) => `<td>${escaparHtml(row[c.chave])}</td>`).join("")}</tr>`
    ).join("");
  }
  totalLabel.textContent = linhas.length === dados.linhas.length
    ? `${dados.linhas.length} registros`
    : `${linhas.length} de ${dados.linhas.length} registros`;
}

/** Baixa as linhas visíveis (já filtradas) como CSV: ";" e BOM, para abrir direto no Excel em português. */
function exportarTabelaCsv(entity) {
  const dados = _tabelas[entity];
  const linhas = linhasFiltradas(entity);
  if (!dados || !linhas.length) { toast("Não há registros para exportar"); return; }
  const cel = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = [dados.colunas.map((c) => cel(c.label)).join(";")]
    .concat(linhas.map((row) => dados.colunas.map((c) => cel(row[c.chave])).join(";")))
    .join("\r\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${entity}_${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`${linhas.length} registros exportados`);
}

function conectarFiltrosTabela(entity) {
  const sec = document.getElementById(`sec-${entity}`);
  if (sec.dataset.filtros === "1") return;       // liga os eventos uma única vez
  sec.dataset.filtros = "1";
  sec.querySelectorAll(".js-filtro, .js-busca").forEach((el) => {
    el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => desenharTabela(entity));
  });
  sec.querySelector(".js-exportar")?.addEventListener("click", () => exportarTabelaCsv(entity));
  sec.querySelector(".js-atualizar")?.addEventListener("click", (e) => {
    // abre a automação que coleta estes dados (mesmo caminho do menu Automações)
    document.querySelector(`.nav-subitem[data-auto="${e.currentTarget.dataset.auto}"]`)?.click();
  });
}

async function carregarTabelaGenerica(entity) {
  const thead = document.getElementById(`thead-${entity}`);
  const tbody = document.getElementById(`tbody-${entity}`);
  const view = document.getElementById(`view-${entity}`);
  const sec = document.getElementById(`sec-${entity}`);
  conectarFiltrosTabela(entity);

  try {
    const data = await apiGet(`/${entity}/lista`);
    const colunas = data.colunas || [];
    _tabelas[entity] = { colunas, linhas: data.linhas || [], extra: data };
    thead.innerHTML = colunas.map((c) => `<th>${escaparHtml(c.label)}</th>`).join("");

    // seletor de turma: só as turmas que aparecem nos dados
    const selTurma = sec.querySelector('.js-filtro[data-key="turma"]');
    if (selTurma) {
      const atual = selTurma.value;
      const turmas = [...new Set(_tabelas[entity].linhas.map((r) => r.turma).filter((t) => t && t !== "—"))].sort();
      selTurma.innerHTML = '<option value="">Todas as turmas</option>' +
        turmas.map((t) => `<option value="${escaparHtml(t)}">${escaparHtml(t)}</option>`).join("");
      selTurma.value = turmas.includes(atual) ? atual : "";
    }

    const resumo = sec.querySelector(".js-resumo");
    if (resumo) resumo.textContent = data.resumo || "";
    desenharTabela(entity);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; color:var(--txt3); padding:24px;">Não foi possível carregar /${escaparHtml(entity)}/lista.</td></tr>`;
    view.querySelector(".js-total").textContent = "—";
    console.warn(`Tabela ${entity}: erro ao carregar`, e);
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
let _alunosCompletoMeta = null;   // resumo do alunos_completo.json devolvido por /alunos/lista
let _alunosBasicoGerado = true;   // alunos.json existe?
let _alunosExtrasCatalogo = [];   // campos que só o cadastro completo traz: [{grupo, rotulo}]

// Ficha do aluno: UMA tela com os dois cadastros. Cada grupo lista os campos do cadastro básico (alunos.json, nomes
// exatamente como o SERE devolve; ver src.automacao.alunos.get_dados_aluno) e, logo depois, os do cadastro completo
// (alunos_completo.json) que pertencem ao mesmo grupo (catálogo vindo de /alunos/lista, src.comum.alunos_unificados).
// Todo campo aparece sempre; sem valor em nenhum dos dois cadastros, mostra "—".
const AL_GROUPS = [
  { label: "Identificação", keys: ["Nome", "CGM", "RG", "CPF", "NIS Estudante", "Nacionalidade"] },
  { label: "Nascimento e origem", keys: ["Data Nascimento", "Sexo", "Cor", "Estado Civil", "Município Nascimento", "UF Nascimento"] },
  { label: "Documentação", keys: ["Data Expedição RG", "Órgão Emissor", "UF RG"] },
  { label: "Família e responsável", keys: ["Mãe", "Pai", "Responsável", "Parentesco", "CPF Responsável", "NIS Responsável"] },
  { label: "Contato", keys: ["Celular Aluno", "Celular Responsável", "Telefone Residencial", "Telefone Comercial", "Email Aluno", "Email Responsável", "Email Google"] },
  { label: "Endereço", keys: ["Endereço", "Número", "Complemento", "Bairro", "CEP", "Cidade", "UF"] },
  { label: "Programas sociais", keys: ["Bolsa Família"] },
  { label: "Perfil socioeconômico", keys: [] },
  { label: "Necessidades especiais", keys: [] },
  { label: "Observação", keys: [] },
];
const AL_VAZIO = "—";

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

// Selo de origem ao lado do rótulo: de onde veio o valor mostrado.
function _tagOrigem(texto, cor) {
  return ` <span style="color:var(--${cor}); font-size:.6rem">· ${texto}</span>`;
}

function _cadastroBadge(aluno) {
  if (aluno._cadastro === "completo") return badge("Completo", "bg-cyan");
  if (aluno._cadastro === "so_completo") return badge("Só completo", "bg-violet");
  return badge("Básico", "bg-muted");
}

// Valor do cadastro básico por rótulo (sem diferenciar maiúsculas); "" se não houver.
function _valorBasico(aluno, chave) {
  const alvo = chave.toLowerCase();
  const k = Object.keys(aluno).find((x) => !x.startsWith("_") && x.toLowerCase() === alvo);
  const v = k === undefined ? "" : aluno[k];
  const s = v === undefined || v === null ? "" : String(v).trim();
  return s === AL_VAZIO ? "" : s;
}

function _buildDetailHTML(aluno) {
  const preenchidos = new Set(aluno._preenchido_completo || []);
  const divergentes = new Map((aluno._divergencias || []).map((d) => [d.rotulo, d]));
  const extrasDoAluno = new Map((aluno._extras || []).map((e) => [e.rotulo, e.valor]));
  const usados = new Set();

  // Um campo da ficha: valor ou "—" quando nenhum dos cadastros tem.
  const campoHtml = (rotulo, valor, tag, mono, aviso) => {
    const vazio = !valor;
    const val = vazio
      ? `<span class="al-field-val al-vazio">${AL_VAZIO}</span>`
      : `<span class="al-field-val${mono ? " mono" : ""}">${escaparHtml(valor)}</span>`;
    return `<div class="al-field-group"${aviso || ""}><span class="al-field-lbl">${escaparHtml(rotulo)}${tag || ""}</span>${val}</div>`;
  };

  const gruposHtml = AL_GROUPS.map((grupo) => {
    let itens = "";
    grupo.keys.forEach((chave) => {
      const valor = _valorBasico(aluno, chave);
      // chave real no cadastro (para não repetir em "Outros")
      Object.keys(aluno).filter((x) => x.toLowerCase() === chave.toLowerCase()).forEach((x) => usados.add(x));
      let tag = "";
      let aviso = "";
      if (valor && preenchidos.has(chave)) tag = _tagOrigem("completo", "cyan");
      const div = divergentes.get(chave);
      if (div) {
        tag += _tagOrigem("⚠ difere do completo", "amber");
        aviso = ` title="${escaparHtml(`Cadastro completo: ${div.completo}`)}"`;
      }
      itens += campoHtml(chave, valor, tag, false, aviso);
    });
    _alunosExtrasCatalogo.filter((e) => e.grupo === grupo.label).forEach((e) => {
      const valor = extrasDoAluno.get(e.rotulo) || "";
      itens += campoHtml(e.rotulo, valor, valor ? _tagOrigem("completo", "cyan") : "", false, "");
    });
    return itens ? `<div class="al-section-ttl">${escaparHtml(grupo.label)}</div>${itens}` : "";
  }).join("");

  // Escola: turma e situação vêm de turmas.json
  const turma = aluno._turma && aluno._turma !== AL_VAZIO ? aluno._turma : "";
  const situacao = aluno._situacao && aluno._situacao !== AL_VAZIO ? aluno._situacao : "";
  const sitS = String(situacao).toLowerCase();
  const corSit = sitS.includes("matriculado") ? "var(--lime)" : sitS.includes("transf") ? "var(--rose)" : "var(--txt2)";
  const escolaHtml = `<div class="al-section-ttl">Escola</div>` +
    `<div class="al-field-group"><span class="al-field-lbl">Turma ${_tagOrigem("turmas.json", "cyan")}</span>${turma ? `<span class="al-field-val">${escaparHtml(turma)}</span>` : `<span class="al-field-val al-vazio">${AL_VAZIO}</span>`}</div>` +
    `<div class="al-field-group"><span class="al-field-lbl">Situação ${_tagOrigem("turmas.json", "cyan")}</span>${situacao ? `<span class="al-field-val" style="color:${corSit}; font-weight:700">${escaparHtml(situacao)}</span>` : `<span class="al-field-val al-vazio">${AL_VAZIO}</span>`}</div>`;

  // Campos do cadastro básico que não pertencem a nenhum grupo acima (só os preenchidos)
  const resto = _alunosCampos.filter((f) => !usados.has(f) && _valorBasico(aluno, f));
  const restoHtml = resto.length
    ? `<div class="al-section-ttl">Outros</div>` + resto.map((f) => campoHtml(f, _valorBasico(aluno, f), "", true, "")).join("")
    : "";

  // Valores diferentes nos dois cadastros: nenhum é sobrescrito; quem usa a tela confere.
  const divs = aluno._divergencias || [];
  const divHtml = divs.length
    ? `<div class="al-section-ttl" style="color:var(--amber)">Diferenças entre o cadastro básico e o completo</div>` +
      divs.map((d) => `<div class="al-field-group"><span class="al-field-lbl">${escaparHtml(d.rotulo)}</span><span class="al-field-val">Básico: ${escaparHtml(d.basico)}<br>Completo: ${escaparHtml(d.completo)}</span></div>`).join("")
    : "";

  // De onde veio cada parte da ficha (e o que falta)
  const notas = [];
  if (aluno._cadastro === "basico") {
    notas.push(_alunosCompletoMeta && !_alunosCompletoMeta.gerado
      ? "O cadastro completo ainda não foi coletado: os campos dele aparecem como —. Rode Automações → Alunos no modo Completo."
      : "Este aluno ainda não foi coletado no modo Completo: os campos do cadastro completo aparecem como —.");
  } else {
    const quando = aluno._coleta_completo ? String(aluno._coleta_completo).replace("T", " ") : "data não registrada";
    notas.push(`Cadastro completo coletado em ${quando}.`);
    if (aluno._cadastro === "so_completo") {
      notas.push(_alunosBasicoGerado
        ? "Este aluno ainda não tem o cadastro básico (rode a automação Alunos no modo Básico): os campos dele aparecem como — quando o completo não os tem."
        : "O cadastro básico (alunos.json) ainda não existe: os campos dele aparecem como — quando o completo não os tem.");
    }
  }
  const origemHtml = `<div class="al-section-ttl">Origem dos dados</div><div class="al-field-group" style="grid-column:1/-1"><span class="al-field-val mono">${escaparHtml(notas.join(" "))}</span></div>`;

  return gruposHtml + escolaHtml + restoHtml + divHtml + origemHtml;
}

function renderAlunosRows() {
  const q = alunosState.search.toLowerCase();

  let dados = _alunosCache.filter((a) => {
    const sit = _getSituacao(a).toLowerCase();
    if (alunosState.filter === "matriculado" && !sit.includes("matriculado")) return false;
    if (alunosState.filter === "transferido" && !sit.includes("transf")) return false;
    if (alunosState.filter === "completo" && a._cadastro === "basico") return false;
    if (alunosState.filter === "basico" && a._cadastro !== "basico") return false;
    if (!q) return true;
    return _alunosCampos.some((f) => String(a[f] || "").toLowerCase().includes(q)) ||
      _getTurma(a).toLowerCase().includes(q) ||
      (a._extras || []).some((e) => String(e.valor || "").toLowerCase().includes(q));
  });

  const { col, dir } = alunosState.sort;
  dados = dados.slice().sort((a, b) => {
    let va, vb;
    if (col === "nome") { va = _getField(a, "Nome"); vb = _getField(b, "Nome"); }
    else if (col === "cgm") { va = _getField(a, "CGM"); vb = _getField(b, "CGM"); }
    else if (col === "turma") { va = _getTurma(a); vb = _getTurma(b); }
    else if (col === "cadastro") { va = String(a._cadastro || ""); vb = String(b._cadastro || ""); }
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
      <td>${_cadastroBadge(a)}${(a._divergencias || []).length ? " " + badge("⚠", "bg-amber") : ""}</td>
    </tr>
    <tr class="al-detail-row" id="${rowId}">
      <td colspan="6"><div class="al-detail-inner">${_buildDetailHTML(a)}</div></td>
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

// Linha de resumo sob os filtros: quantos alunos já têm o cadastro completo (alunos_completo.json).
function _renderAlunosInfo() {
  const el = document.getElementById("alunos-info");
  if (!el) return;
  const m = _alunosCompletoMeta;
  if (!m) { el.style.display = "none"; return; }
  const total = _alunosCache.length;
  const comCompleto = _alunosCache.filter((a) => a._cadastro !== "basico").length;
  let txt;
  if (!_alunosBasicoGerado) {
    txt = "O cadastro básico (alunos.json) ainda não existe: os campos dele aparecem como — quando o cadastro completo não os tem. " +
      (m.gerado ? `Cadastro completo coletado para ${comCompleto} aluno(s).` : "Rode Automações → Alunos para coletar.");
  } else if (!m.gerado) {
    txt = "Cadastro completo ainda não coletado: a tabela mostra só o cadastro básico. Rode Automações → Alunos no modo Completo para ver os demais campos.";
  } else {
    txt = `Cadastro completo coletado para ${comCompleto} de ${total} aluno(s)` +
      (m.atualizado_em ? ` · arquivo atualizado em ${m.atualizado_em}` : "") +
      (m.so_completo ? ` · ${m.so_completo} só com cadastro completo` : "") +
      (m.com_divergencia ? ` · ${m.com_divergencia} com diferenças entre os cadastros (⚠)` : "") + ".";
  }
  el.textContent = txt;
  el.style.display = "";
}

async function carregarAlunos() {
  const cnt = document.getElementById("alunos-cnt");
  cnt.textContent = "Carregando…";

  try {
    const data = await apiGet("/alunos/lista");
    _alunosCache = data.alunos || [];
    _alunosCampos = data.campos || [];
    _alunosCompletoMeta = data.completo || null;
    _alunosBasicoGerado = !(data.basico && data.basico.gerado === false);
    _alunosExtrasCatalogo = data.extras_catalogo || [];
    _renderAlunosInfo();
  } catch (e) {
    cnt.textContent = "—";
    document.getElementById("alunos-tbody").innerHTML =
      `<tr><td colspan="6" style="text-align:center; color:var(--txt3); padding:24px;">Endpoint /alunos/lista ainda não conectado.</td></tr>`;
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

/* ---------- Alunos fora do raio (mesma tela "Fora do Raio" do index.html) ---------- */

const foraState = { filter: "all", search: "", sort: { col: "dist", dir: -1 } };
let _foraDados = null;

function _foraFiltradas() {
  if (!_foraDados) return [];
  const q = semAcento(foraState.search.trim());
  let dados = _foraDados.linhas.slice();
  if (foraState.filter === "has-doc") dados = dados.filter((a) => a.tem_comprovante === true);
  if (foraState.filter === "no-doc") dados = dados.filter((a) => a.tem_comprovante === false);
  if (q) dados = dados.filter((a) => semAcento(a.nome).includes(q) || String(a.cep || "").includes(q) || String(a.cgm || "").includes(q));
  const { col, dir } = foraState.sort;
  return dados.sort((a, b) => {
    if (col === "dist") return (a.distancia_km - b.distancia_km) * dir;
    if (col === "nome") return String(a.nome).localeCompare(String(b.nome)) * dir;
    if (col === "turma") return String(a.turma || "").localeCompare(String(b.turma || "")) * dir;
    return String(a.cgm || "").localeCompare(String(b.cgm || "")) * dir;
  });
}

function renderForaRows() {
  const dados = _foraFiltradas();
  const tbody = document.getElementById("fora-tbody");
  const vazio = document.getElementById("fora-empty");
  if (!dados.length) {
    tbody.innerHTML = "";
    document.getElementById("fora-empty-msg").textContent = _foraDados?.linhas.length
      ? "Nenhum resultado."
      : 'Nenhum aluno fora do raio (ou a análise ainda não foi executada). Use "Atualizar dados".';
    vazio.style.display = "";
    return;
  }
  vazio.style.display = "none";
  const maior = _foraDados.maior_km;
  tbody.innerHTML = dados.map((a) => `<tr>
    <td class="td-name">${escaparHtml(a.nome)}<small>CGM: ${escaparHtml(a.cgm || "—")}</small></td>
    <td class="td-mono">${escaparHtml(a.turma || "—")}</td>
    <td>${barraDistancia(a.distancia_km, maior)}</td>
    <td class="td-mono">${escaparHtml(a.cgm || "—")}</td>
    <td class="td-mono">${escaparHtml(a.cep || "—")}</td>
    <td>${a.tem_comprovante === true ? badge(escaparHtml(a.comprovante), "bg-lime")
      : a.tem_comprovante === false ? badge("Não encontrado", "bg-rose") : '<span class="td-mono" title="Os documentos do PC ainda não foram analisados">—</span>'}</td>
    <td>${_docChips(a.docs_pc || [], a.docs_endereco || [])}</td>
  </tr>`).join("");
}

function ligarAcoesTela(entity) {
  const sec = document.getElementById(`sec-${entity}`);
  if (sec.dataset.acoes === "1") return;
  sec.dataset.acoes = "1";
  sec.querySelector(".js-exportar")?.addEventListener("click", () => exportarTabelaCsv(entity));
  sec.querySelector(".js-atualizar")?.addEventListener("click", (e) => {
    document.querySelector(`.nav-subitem[data-auto="${e.currentTarget.dataset.auto}"]`)?.click();
  });
}

async function carregarForaDoRaio() {
  const sec = document.getElementById("sec-fora-do-raio");
  ligarAcoesTela("fora-do-raio");
  try {
    const data = await apiGet("/fora-do-raio/lista");
    _foraDados = data;
    _tabelas["fora-do-raio"] = { colunas: data.colunas || [], linhas: data.linhas || [], extra: data };
    _FILTRO_CUSTOM["fora-do-raio"] = _foraFiltradas;
  } catch (e) {
    _foraDados = { linhas: [], maior_km: 0 };
    document.getElementById("fora-tbody").innerHTML = "";
    document.getElementById("fora-empty-msg").textContent = "Não foi possível carregar /fora-do-raio/lista.";
    document.getElementById("fora-empty").style.display = "";
    console.warn("Fora do raio: erro ao carregar", e);
    return;
  }

  desenharExtrasTabela("fora-do-raio", _foraDados);

  // sem os documentos do PC não dá para afirmar "com/sem comprovante": esses filtros somem
  const total = _foraDados.linhas.length;
  const com = _foraDados.linhas.filter((a) => a.tem_comprovante === true).length;
  const rotulos = { all: `Todos (${total})`, "has-doc": `Com comp. endereço (${com})`, "no-doc": `Sem comprovante (${total - com})` };
  sec.querySelectorAll("[data-ff]").forEach((b) => {
    b.textContent = rotulos[b.dataset.ff];
    b.style.display = !_foraDados.tem_docs_pc && b.dataset.ff !== "all" ? "none" : "";
  });
  if (!_foraDados.tem_docs_pc && foraState.filter !== "all") foraState.filter = "all";
  sec.querySelectorAll("[data-ff]").forEach((b) => b.classList.toggle("active", b.dataset.ff === foraState.filter));

  if (sec.dataset.ligada !== "1") {
    sec.dataset.ligada = "1";
    sec.querySelectorAll("[data-ff]").forEach((btn) => {
      btn.addEventListener("click", () => {
        sec.querySelectorAll("[data-ff]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        foraState.filter = btn.dataset.ff;
        renderForaRows();
      });
    });
    sec.querySelectorAll("th[data-sf]").forEach((th) => {
      th.addEventListener("click", () => {
        const col = th.dataset.sf;
        if (foraState.sort.col === col) foraState.sort.dir *= -1;
        else { foraState.sort.col = col; foraState.sort.dir = 1; }
        sec.querySelectorAll("th[data-sf]").forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
        th.classList.add(foraState.sort.dir === 1 ? "sort-asc" : "sort-desc");
        renderForaRows();
      });
    });
    document.getElementById("fora-q").addEventListener("input", (e) => { foraState.search = e.target.value; renderForaRows(); });
  }
  renderForaRows();
}

/* ---------- Encaminhamentos do SUS (mesma tela "Encaminhamentos" do index.html) ---------- */

const encState = { search: "", filter: "all" };
let _encDados = null;

function renderEncamList() {
  const q = semAcento(encState.search.trim());
  let dados = _encDados?.alunos || [];
  if (encState.filter === "com") dados = dados.filter((a) => !a.erro && a.encaminhamentos.length > 0);
  if (encState.filter === "sem-cpf") dados = dados.filter((a) => !!a.erro);
  if (q) {
    dados = dados.filter((a) => semAcento(a.nome).includes(q) || String(a.cpf || "").includes(q) ||
      a.encaminhamentos.some((e) => semAcento(e.procedimento).includes(q)));
  }
  const el = document.getElementById("encam-list");
  if (!dados.length) {
    el.innerHTML = `<div class="empty"><span data-icon="search"></span>${_encDados?.alunos.length ? "Nenhum resultado."
      : 'Nenhum encaminhamento encontrado. Use "Atualizar dados" para consultar o SISREG.'}</div>`;
    aplicarIconesDOM(el);
    return;
  }
  el.innerHTML = dados.map((a) => {
    const itens = a.encaminhamentos.map((e) => `
      <div class="encam-item">
        <div class="encam-proc">${escaparHtml(e.procedimento)}</div>
        <div class="encam-fila">Fila: <strong>${escaparHtml(e.posicao_fila || "—")}</strong></div>
        <div class="encam-data">Solicitado em ${escaparHtml(e.data_solicitacao || "—")} · Nasc.: ${escaparHtml(e.data_nascimento || "—")}</div>
      </div>`).join("");
    return `<div class="encam-card">
      <div class="encam-nome">${escaparHtml(a.nome)}</div>
      <div class="encam-cpf">CPF: ${escaparHtml(a.cpf || "—")}${a.turma && a.turma !== "—" ? ` · ${escaparHtml(a.turma)}` : ""}</div>
      ${a.erro ? `<div class="encam-erro">${icon("alertFile")} ${escaparHtml(a.erro)}</div>` : ""}
      ${a.encaminhamentos.length ? `<div class="encam-list">${itens}</div>`
        : (!a.erro ? '<div style="font-family:var(--mono);font-size:.7rem;color:var(--txt3);margin-top:8px">Sem encaminhamentos ativos</div>' : "")}
    </div>`;
  }).join("");
}

async function carregarEncaminhamentos() {
  const sec = document.getElementById("sec-encaminhamentos");
  ligarAcoesTela("encaminhamentos");
  try {
    _encDados = await apiGet("/encaminhamentos/lista");
    _tabelas.encaminhamentos = { colunas: _encDados.colunas || [], linhas: _encDados.linhas || [], extra: _encDados };
  } catch (e) {
    _encDados = { alunos: [] };
    document.getElementById("encam-list").innerHTML =
      '<div class="empty">Não foi possível carregar /encaminhamentos/lista.</div>';
    console.warn("Encaminhamentos: erro ao carregar", e);
    return;
  }
  desenharExtrasTabela("encaminhamentos", _encDados);

  const todos = _encDados.alunos;
  const rotulos = {
    all: `Todos (${todos.length})`,
    com: `Com encaminhamentos (${todos.filter((a) => !a.erro && a.encaminhamentos.length).length})`,
    "sem-cpf": `CPF inválido (${todos.filter((a) => a.erro).length})`,
  };
  sec.querySelectorAll("[data-ef]").forEach((b) => { b.textContent = rotulos[b.dataset.ef]; });

  if (sec.dataset.ligada !== "1") {
    sec.dataset.ligada = "1";
    sec.querySelectorAll("[data-ef]").forEach((btn) => {
      btn.addEventListener("click", () => {
        sec.querySelectorAll("[data-ef]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        encState.filter = btn.dataset.ef;
        renderEncamList();
      });
    });
    document.getElementById("enc-q").addEventListener("input", (e) => { encState.search = e.target.value; renderEncamList(); });
  }
  renderEncamList();
}

/* ---------- Helpers das telas Funcionários / Pré-matrícula / Transferidos ---------- */

/** Paginação do protótipo: "Exibindo 1–25 de N" + botões ‹ 1 2 … N ›. */
function renderPaginacao(infoEl, btnsEl, total, page, pageSize, irPara) {
  if (!total) { infoEl.textContent = "Nenhum resultado"; btnsEl.innerHTML = ""; return; }
  const paginas = Math.max(1, Math.ceil(total / pageSize));
  infoEl.textContent = `Exibindo ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} de ${total}`;
  const faixa = [];
  if (paginas <= 7) for (let i = 1; i <= paginas; i++) faixa.push(i);
  else {
    faixa.push(1);
    if (page > 3) faixa.push("…");
    for (let i = Math.max(2, page - 1); i <= Math.min(paginas - 1, page + 1); i++) faixa.push(i);
    if (page < paginas - 2) faixa.push("…");
    faixa.push(paginas);
  }
  btnsEl.innerHTML = `<button class="pag-btn" data-p="${page - 1}" ${page === 1 ? "disabled" : ""} title="Página anterior">‹</button>` +
    faixa.map((p) => (p === "…" ? '<span class="pag-ellipsis">···</span>'
      : `<button class="pag-btn${p === page ? " active" : ""}" data-p="${p}">${p}</button>`)).join("") +
    `<button class="pag-btn" data-p="${page + 1}" ${page === paginas ? "disabled" : ""} title="Próxima página">›</button>`;
  btnsEl.querySelectorAll("[data-p]").forEach((b) => b.addEventListener("click", () => irPara(Number(b.dataset.p))));
}

/** Cabeçalhos ordenáveis: atributo `attr` (ex.: data-fs) guarda a coluna; chama `redesenhar` ao mudar. */
function ligarOrdenacao(sec, attr, state, redesenhar) {
  sec.querySelectorAll(`th[${attr}]`).forEach((th) => {
    th.addEventListener("click", () => {
      const col = th.getAttribute(attr);
      if (state.sort.col === col) state.sort.dir *= -1;
      else { state.sort.col = col; state.sort.dir = 1; }
      sec.querySelectorAll(`th[${attr}]`).forEach((h) => h.classList.remove("sort-asc", "sort-desc"));
      th.classList.add(state.sort.dir === 1 ? "sort-asc" : "sort-desc");
      if ("page" in state) state.page = 1;
      redesenhar();
    });
  });
}

/** Liga um grupo de "pílulas" (atributo `attr`, ex.: data-fg) a state[campo]. */
function ligarPilulas(sec, attr, state, campo, redesenhar) {
  sec.querySelectorAll(`[${attr}]`).forEach((btn) => {
    btn.addEventListener("click", () => {
      sec.querySelectorAll(`[${attr}]`).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state[campo] = btn.getAttribute(attr);
      if ("page" in state) state.page = 1;
      redesenhar();
    });
  });
}

/** Linha de detalhe expansível (mesmo botão "+" do Alunos); `montar` devolve o HTML interno na 1ª abertura. */
function ligarExpansao(tbody, montar) {
  tbody.querySelectorAll(".al-expand-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const linha = document.getElementById(btn.dataset.btn);
      const aberta = linha.classList.toggle("open");
      btn.classList.toggle("open", aberta);
      btn.title = aberta ? "Fechar detalhes" : "Ver detalhes";
      const dentro = linha.querySelector(".al-detail-inner");
      if (aberta && !dentro.dataset.pronto) { dentro.innerHTML = montar(Number(btn.dataset.i)); dentro.dataset.pronto = "1"; }
    });
  });
}

const _campo = (rotulo, valor, mono = false) => `<div class="al-field-group"><span class="al-field-lbl">${escaparHtml(rotulo)}</span><span class="al-field-val${mono ? " mono" : ""}">${escaparHtml(valor || "—")}</span></div>`;
const _secao = (titulo) => `<div class="al-section-ttl">${escaparHtml(titulo)}</div>`;

function _carregarVazio(tbodyId, emptyId, msgId, texto) {
  document.getElementById(tbodyId).innerHTML = "";
  document.getElementById(msgId).textContent = texto;
  document.getElementById(emptyId).style.display = "";
}

function _formatarTelefone(t) {
  const d = String(t || "").replace(/\D/g, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return t || "—";
}

/* ---------- Funcionários (mesma tela "Funcionários" do index.html) ---------- */

const funcState = { grupo: "todos", search: "", sexo: "todos", vinculo: "todos", pageSize: 25, page: 1, sort: { col: "nome", dir: 1 } };
let _funcDados = null;

const _FUNC_ROTULOS = {
  nome_completo: "Nome completo", data_nascimento: "Data de nascimento", sexo: "Sexo", raca_cor: "Raça/cor", nis: "NIS / PIS",
  rg: "RG", orgao_emissor_rg: "Órgão emissor", uf_rg: "UF do RG", data_expedicao_rg: "Expedição do RG", complemento_rg: "Complemento do RG",
  nome_mae: "Nome da mãe", municipio_nascimento: "Município de nascimento", uf_nascimento: "UF de nascimento",
  tipo_nacionalidade: "Nacionalidade", pais_origem: "País de origem", email: "E-mail", telefone: "Telefone",
  cep: "CEP", endereco: "Endereço", numero: "Número", complemento: "Complemento", bairro: "Bairro",
  municipio_endereco: "Município", uf_endereco: "UF", zona_residencial: "Zona residencial",
  tipo_certidao: "Tipo de certidão", nome_cartorio: "Cartório", numero_termo: "Termo", folha: "Folha", livro: "Livro", uf_cartorio: "UF do cartório",
  escolaridade: "Escolaridade", curso_superior: "Curso superior", deficiencias: "Deficiências",
  vinculo: "Vínculo", matricula: "Matrícula", cargo_prefeitura: "Cargo na Prefeitura", data_admissao: "Data de admissão", matriculas: "Matrículas nesta escola", observacao_vinculo: "Observação do vínculo", situacao_na_escola: "Está na escola?", local_holerite: "Local de trabalho (holerite)", revisar: "A revisar",
};
const _FUNC_GRUPOS = [
  ["Identificação", ["nome_completo", "data_nascimento", "sexo", "raca_cor", "nis", "rg", "orgao_emissor_rg", "uf_rg", "data_expedicao_rg", "complemento_rg"]],
  ["Filiação e naturalidade", ["nome_mae", "municipio_nascimento", "uf_nascimento", "tipo_nacionalidade", "pais_origem"]],
  ["Vínculo com a Prefeitura", ["vinculo", "matricula", "cargo_prefeitura", "data_admissao", "matriculas", "situacao_na_escola", "local_holerite", "observacao_vinculo", "revisar"]],
  ["Contato", ["email", "telefone"]],
  ["Endereço", ["endereco", "numero", "complemento", "bairro", "cep", "municipio_endereco", "uf_endereco", "zona_residencial"]],
  ["Certidão", ["tipo_certidao", "nome_cartorio", "numero_termo", "folha", "livro", "uf_cartorio"]],
  ["Formação", ["escolaridade", "curso_superior", "deficiencias"]],
];

function _badgeFuncao(f) {
  const cor = { Docente: "bg-blue", "Direção": "bg-violet", Pedagogos: "bg-cyan", Auxiliares: "bg-amber" }[f.grupo] || "bg-muted";
  const curto = { Docente: "Docente", "Direção": "Diretor(a)", Pedagogos: "Pedagogo(a)" }[f.grupo]
    || (f.grupo === "Auxiliares" ? (semAcento(f.funcao).includes("secretari") ? "Secretário(a)" : "Auxiliar") : (f.funcao || "—"));
  return `<span title="${escaparHtml(f.funcao || "")}">${badge(escaparHtml(curto), cor)}</span>`;
}

function _funcFiltrados() {
  if (!_funcDados) return [];
  const q = semAcento(funcState.search.trim());
  let dados = _funcDados.funcionarios.filter((f) => {
    if (funcState.grupo !== "todos" && f.grupo !== funcState.grupo) return false;
    if (funcState.sexo !== "todos" && f.sexo !== funcState.sexo) return false;
    if (funcState.vinculo === "revisar") { if (!(f.revisar && f.revisar.length)) return false; }
    else if (funcState.vinculo === "multiplas") { if (!f.multiplas_matriculas) return false; }
    else if (funcState.vinculo !== "todos" && f.vinculo !== funcState.vinculo) return false;
    return !q || [f.nome, f.cpf, f.email, f.telefone, f.funcao, f.formacao].some((v) => semAcento(v).includes(q));
  });
  const { col, dir } = funcState.sort;
  return dados.sort((a, b) => semAcento(a[col]).localeCompare(semAcento(b[col]), "pt-BR") * dir);
}

function _detalheFuncionario(f) {
  const d = { ...f.detalhe };
  if (f.cpf) d._cpf = f.cpf;
  let html = _secao("Resumo") + _campo("Nome", f.nome) + _campo("Função", f.funcao) + _campo("CPF", f.cpf, true) +
    _campo("Turmas", f.lista_turmas.length ? f.lista_turmas.join(" · ") : "—");
  const usados = new Set();
  _FUNC_GRUPOS.forEach(([titulo, chaves]) => {
    const itens = chaves.filter((k) => d[k] !== undefined && d[k] !== null && d[k] !== "");
    itens.forEach((k) => usados.add(k));
    if (itens.length) html += _secao(titulo) + itens.map((k) => _campo(_FUNC_ROTULOS[k] || k, String(d[k]), ["rg", "nis", "cep", "telefone"].includes(k))).join("");
  });
  if (!f.tem_cadastro_completo) html += `<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-val" style="color:var(--txt3)">Cadastro individual ainda não coletado (rode a coleta completa de servidores).</span></div>`;
  return html;
}

function renderFuncRows() {
  const todos = _funcFiltrados();
  const total = todos.length;
  const paginas = Math.max(1, Math.ceil(total / funcState.pageSize));
  funcState.page = Math.min(funcState.page, paginas);
  const inicio = (funcState.page - 1) * funcState.pageSize;
  const pagina = todos.slice(inicio, inicio + funcState.pageSize);
  document.getElementById("func-cnt").textContent = `${total} / ${_funcDados.funcionarios.length}`;
  const tbody = document.getElementById("func-tbody");
  renderPaginacao(document.getElementById("func-pag-info"), document.getElementById("func-pag-btns"), total, funcState.page, funcState.pageSize,
    (p) => { funcState.page = p; renderFuncRows(); });
  if (!pagina.length) {
    _carregarVazio("func-tbody", "func-empty", "func-empty-msg", _funcDados.funcionarios.length ? "Nenhum funcionário encontrado." : 'Nenhum funcionário coletado. Rode a coleta de funcionários e atualize.');
    return;
  }
  document.getElementById("func-empty").style.display = "none";
  tbody.innerHTML = pagina.map((f, i) => {
    const rowId = `fn-row-${inicio + i}`;
    const iniciais = String(f.nome).split(" ").filter(Boolean).slice(0, 2).map((w) => w[0]).join("");
    const sexo = f.sexo === "F" ? badge("Feminino", "bg-violet") : f.sexo === "M" ? badge("Masculino", "bg-blue") : badge("—", "bg-muted");
    return `<tr>
      <td style="width:36px; text-align:center"><button class="al-expand-btn" data-btn="${rowId}" data-i="${inicio + i}" title="Ver detalhes">+</button></td>
      <td class="td-name"><div style="display:flex; align-items:center; gap:7px">
        <div style="width:28px; height:28px; border-radius:50%; background:linear-gradient(135deg,var(--cyan),var(--violet)); display:flex; align-items:center; justify-content:center; font-size:.65rem; font-weight:700; color:#fff; flex-shrink:0">${escaparHtml(iniciais)}</div>
        <span>${escaparHtml(f.nome)}</span>${f.terceirizado ? badge("Terceirizado", "bg-amber") : ""}${f.na_escola === false ? badge("Outro local", "bg-rose") : ""}</div></td>
      <td>${_badgeFuncao(f)}</td>
      <td class="td-mono hide-sm">${f.email ? `<a href="mailto:${escaparHtml(f.email)}" style="color:var(--cyan); text-decoration:none">${escaparHtml(f.email)}</a>` : "—"}</td>
      <td class="td-mono hide-sm">${escaparHtml(_formatarTelefone(f.telefone))}</td>
      <td>${sexo}</td>
      <td class="td-mono">${escaparHtml(f.cpf || "—")}</td>
      <td class="td-mono hide-sm" style="font-size:.72rem; color:var(--txt3)">${escaparHtml(f.formacao || "—")}</td>
    </tr>
    <tr class="al-detail-row" id="${rowId}"><td colspan="8"><div class="al-detail-inner"></div></td></tr>`;
  }).join("");
  ligarExpansao(tbody, (i) => _detalheFuncionario(todos[i]));
}

// Aviso quando a última coleta COMPLETA de funcionários foi interrompida (cancelada, erro ou o programa caiu).
function _renderAvisoColetaFuncionarios(info) {
  const el = document.getElementById("func-aviso-coleta");
  if (!el) return;
  if (!info) { el.style.display = "none"; el.innerHTML = ""; return; }
  const quando = info.atualizado_em ? ` <span style="color:var(--txt3)">(${escaparHtml(info.atualizado_em)})</span>` : "";
  const pend = (info.pendentes || []).length
    ? `<div class="aviso-coleta-pend">Sem atualização: ${escaparHtml(info.pendentes.slice(0, 15).join(", "))}${info.pendentes.length > 15 ? ` e mais ${info.pendentes.length - 15}` : ""}.</div>`
    : "";
  el.innerHTML = `<b>⚠ Coleta incompleta.</b> ${escaparHtml(info.aviso)}${quando}${pend}`;
  el.style.display = "";
}

async function carregarFuncionarios() {
  const sec = document.getElementById("sec-funcionarios");
  ligarAcoesTela("funcionarios");
  try {
    _funcDados = await apiGet("/funcionarios/lista");
    _tabelas.funcionarios = { colunas: _funcDados.colunas || [], linhas: _funcDados.funcionarios || [], extra: _funcDados };
    _FILTRO_CUSTOM.funcionarios = _funcFiltrados;
  } catch (e) {
    _funcDados = { funcionarios: [] };
    _carregarVazio("func-tbody", "func-empty", "func-empty-msg", "Não foi possível carregar /funcionarios/lista.");
    console.warn("Funcionários: erro ao carregar", e);
    return;
  }
  desenharExtrasTabela("funcionarios", _funcDados);
  _renderAvisoColetaFuncionarios(_funcDados.coleta_completo);
  const c = _funcDados.contagem || {};
  const rotulos = { todos: "Todos", Docente: "Docentes", "Direção": "Direção", Pedagogos: "Pedagogos", Auxiliares: "Auxiliares", Outros: "Outros" };
  sec.querySelectorAll("[data-fg]").forEach((b) => {
    const g = b.dataset.fg;
    b.textContent = `${rotulos[g]} (${g === "todos" ? _funcDados.funcionarios.length : (c[g] || 0)})`;
  });
  if (sec.dataset.ligada !== "1") {
    sec.dataset.ligada = "1";
    ligarPilulas(sec, "data-fg", funcState, "grupo", renderFuncRows);
    ligarOrdenacao(sec, "data-fs", funcState, renderFuncRows);
    document.getElementById("func-q").addEventListener("input", (e) => { funcState.search = e.target.value; funcState.page = 1; renderFuncRows(); });
    document.getElementById("func-sexo").addEventListener("change", (e) => { funcState.sexo = e.target.value; funcState.page = 1; renderFuncRows(); });
    document.getElementById("func-vinculo").addEventListener("change", (e) => { funcState.vinculo = e.target.value; funcState.page = 1; renderFuncRows(); });
    document.getElementById("func-pagesize").addEventListener("change", (e) => { funcState.pageSize = parseInt(e.target.value, 10); funcState.page = 1; renderFuncRows(); });
  }
  renderFuncRows();
}

/* ---------- Pré-matrícula (mesma tela "Pré-Matrícula" do index.html, somente leitura) ---------- */

const pmState = { tab: "geral", search: "", pageSize: 25, page: 1, sort: { col: "nome_aluno", dir: 1 } };
let _pmDados = null;

const _pmSituacaoBadge = (s) => (s === "matriculado" ? badge("Matriculado", "bg-lime") : s === "cancelado" ? badge("Cancelado", "bg-rose") : badge("Pendente", "bg-amber"));

function _pmFiltrados() {
  if (!_pmDados) return [];
  const q = semAcento(pmState.search.trim());
  let dados = _pmDados.cadastros;
  const aba = { matriculados: "matriculado", cancelados: "cancelado", pendentes: "pendente" }[pmState.tab];
  if (aba) dados = dados.filter((c) => c.situacao === aba);
  if (q) dados = dados.filter((c) => [c.nome_aluno, c.nome_responsavel, c.cpf, c.turma_matriculada].some((v) => semAcento(v).includes(q)));
  const { col, dir } = pmState.sort;
  const chave = (c) => (col === "_turmas" ? c.intencoes.map((i) => i.turma).join(", ") : c[col]);
  return [...dados].sort((a, b) => String(chave(a) || "").localeCompare(String(chave(b) || ""), "pt-BR") * dir);
}

function _pmCabecalho() {
  const base = '<th style="width:36px"></th><th data-pms="nome_aluno">Aluno</th><th>CPF</th><th>Responsável</th>';
  if (pmState.tab === "matriculados") return `<tr>${base}<th>Turma</th></tr>`;
  if (pmState.tab === "cancelados") return `<tr>${base}<th>Motivo da Recusa</th></tr>`;
  return `<tr>${base}<th>Telefone</th><th data-pms="situacao">Situação</th><th data-pms="_turmas">Turma(s) de Intenção</th></tr>`;
}

function _pmDetalhe(c) {
  const criterios = c.criterios.length
    ? c.criterios.map((x) => `<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-val" style="white-space:pre-line">${escaparHtml(x)}</span></div>`).join("")
    : '<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-val">Nenhum critério registrado.</span></div>';
  const intencoes = c.intencoes.length
    ? `<div style="grid-column:1/-1" class="tbl-wrap"><table><thead><tr><th>Turma</th><th>Posição</th><th>Pontuação</th><th>Tipo</th><th>Na última coleta</th></tr></thead><tbody>${c.intencoes.map((i) =>
        `<tr><td>${escaparHtml(i.turma)}</td><td class="td-mono">${escaparHtml(i.pos ?? "—")}</td><td class="td-mono">${escaparHtml(i.pontuacao ?? "—")}</td><td>${escaparHtml(i.tipo ?? "—")}</td><td>${i.presente_na_ultima_coleta === true ? "Sim" : i.presente_na_ultima_coleta === false ? "Não" : "—"}</td></tr>`).join("")}</tbody></table></div>`
    : '<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-val" style="color:var(--txt3)">Sem registros em turmas de intenção.</span></div>';
  const opcoes = c.opcoes.length
    ? `<div style="grid-column:1/-1" class="tbl-wrap"><table><thead><tr><th>Escola</th><th>Situação</th><th>Motivo / observação</th></tr></thead><tbody>${c.opcoes.map((o) =>
        `<tr><td>${escaparHtml(o.escola || "—")}</td><td>${escaparHtml(o.situacao || "—")}</td><td>${escaparHtml(o.motivo_cancelamento || o.observacao || "—")}</td></tr>`).join("")}</tbody></table></div>`
    : "";
  return _secao("Dados do Cadastro") + _campo("Nome do aluno", c.nome_aluno) + _campo("CPF", c.cpf, true) + _campo("Responsável", c.nome_responsavel) +
    _campo("Telefone", c.telefone, true) + _campo("E-mail", c.email) + `<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-lbl">Endereço</span><span class="al-field-val">${escaparHtml(c.endereco)}</span></div>` +
    _secao("Critérios Informados") + criterios + _secao("Turmas de Intenção") + intencoes +
    (opcoes ? _secao("Escolas Escolhidas") + opcoes : "") +
    _secao("Situação da Matrícula") + `<div class="al-field-group"><span class="al-field-lbl">Situação</span><span class="al-field-val">${_pmSituacaoBadge(c.situacao)}</span></div>` +
    (c.situacao === "matriculado" ? _campo("Turma matriculada", c.turma_matriculada) + _campo("Escola", c.escola_matriculada) : "") +
    (c.situacao === "cancelado" ? `<div class="al-field-group" style="grid-column:1/-1"><span class="al-field-lbl">Motivo da recusa</span><span class="al-field-val">${escaparHtml(c.motivo_cancelamento || "—")}</span></div>` : "");
}

function renderPmRows() {
  const todos = _pmFiltrados();
  const thead = document.getElementById("pm-thead");
  thead.innerHTML = _pmCabecalho();
  thead.querySelectorAll("th[data-pms]").forEach((th) => {
    th.style.cursor = "pointer";
    if (pmState.sort.col === th.dataset.pms) th.classList.add(pmState.sort.dir === 1 ? "sort-asc" : "sort-desc");
    th.addEventListener("click", () => {
      if (pmState.sort.col === th.dataset.pms) pmState.sort.dir *= -1;
      else { pmState.sort.col = th.dataset.pms; pmState.sort.dir = 1; }
      pmState.page = 1;
      renderPmRows();
    });
  });
  document.getElementById("pm-cnt").textContent = `${todos.length} cadastro(s)`;
  const total = todos.length;
  const paginas = Math.max(1, Math.ceil(total / pmState.pageSize));
  pmState.page = Math.min(pmState.page, paginas);
  const inicio = (pmState.page - 1) * pmState.pageSize;
  renderPaginacao(document.getElementById("pm-pag-info"), document.getElementById("pm-pag-btns"), total, pmState.page, pmState.pageSize,
    (p) => { pmState.page = p; renderPmRows(); });
  if (!total) {
    _carregarVazio("pm-tbody", "pm-empty", "pm-empty-msg", _pmDados.cadastros.length ? "Nenhum resultado."
      : 'Nenhum cadastro de pré-matrícula coletado. Use "Atualizar dados" para rodar a coleta.');
    return;
  }
  document.getElementById("pm-empty").style.display = "none";
  const colspan = pmState.tab === "geral" || pmState.tab === "pendentes" ? 7 : 5;
  document.getElementById("pm-tbody").innerHTML = todos.slice(inicio, inicio + pmState.pageSize).map((c, i) => {
    const rowId = `pm-det-${inicio + i}`;
    const comum = `<td style="text-align:center"><button class="al-expand-btn" data-btn="${rowId}" data-i="${inicio + i}" title="Ver cadastro completo">+</button></td>
      <td class="td-name">${escaparHtml(c.nome_aluno)}<small>CPF: ${escaparHtml(c.cpf)}</small></td>
      <td class="td-mono">${escaparHtml(c.cpf)}</td><td>${escaparHtml(c.nome_responsavel)}</td>`;
    let resto;
    if (pmState.tab === "matriculados") resto = `<td>${escaparHtml(c.turma_matriculada || "—")}</td>`;
    else if (pmState.tab === "cancelados") resto = `<td style="white-space:pre-line">${escaparHtml(c.motivo_cancelamento || "—")}</td>`;
    else resto = `<td class="td-mono" style="font-size:.75rem">${escaparHtml(c.telefone)}</td><td>${_pmSituacaoBadge(c.situacao)}</td>
      <td>${c.intencoes.length ? c.intencoes.map((x) => `<span class="badge bg-muted">${escaparHtml(x.turma)}${x.pos ? " · #" + escaparHtml(x.pos) : ""}</span>`).join(" ") : '<span style="color:var(--txt3); font-size:.75rem">—</span>'}</td>`;
    return `<tr>${comum}${resto}</tr><tr class="al-detail-row" id="${rowId}"><td colspan="${colspan}"><div class="al-detail-inner"></div></td></tr>`;
  }).join("");
  ligarExpansao(document.getElementById("pm-tbody"), (i) => _pmDetalhe(todos[i]));
}

/* ---------- Executar pré-matrícula dentro da própria tela ---------- */
/* Usa as mesmas rotas do menu Automações (chave "prematricula_completa"): /executar, /status e /cancelar. */

const PM_CHAVE = "prematricula_completa";
const PM_ETAPAS = [
  { n: "1", rotulo: "Coleta da fila", marca: /Etapa 1 conclu/i },
  { n: "2", rotulo: "Cadastros dos CPFs", marca: /Etapa 2 conclu/i },
  { n: "4", rotulo: "Pendentes", marca: /Etapa 4 conclu/i, pulada: /Etapa 4 pulada/i },
  { n: "3", rotulo: "Contatos", marca: null },
];
let _pmExecTimer = null;
let _pmExecUltimoStatus = "";

/** Desenha as etapas a partir do log: feita = "Etapa N concluída"; a primeira não feita é a ativa. */
function _pmDesenharEtapas(logs, status) {
  const texto = (logs || []).join("\n");
  let ativaMarcada = false;
  document.getElementById("pm-etapas").innerHTML = PM_ETAPAS.map((e) => {
    let estado = "";
    if (e.pulada && e.pulada.test(texto)) estado = "pulada";
    else if (status === "concluido" || (e.marca && e.marca.test(texto))) estado = "feita";
    else if (!ativaMarcada) {
      ativaMarcada = true;
      estado = status === "executando" ? "ativa" : (status === "erro" || status === "cancelado") ? "falha" : "";
    }
    const marca = estado === "feita" ? "✓" : estado === "falha" ? "✗" : e.n;
    return `<span class="pm-etapa ${estado}">${marca} ${escaparHtml(e.rotulo)}</span>`;
  }).join("");
}

function _pmExecMostrar(s) {
  const status = s.status || "nunca_executado";
  const rotulos = { executando: s.cancelando ? "cancelando…" : "executando", concluido: "concluído", erro: "erro", cancelado: "cancelado", nunca_executado: "parado" };
  document.getElementById("pm-exec-status").textContent = rotulos[status] || status;
  const executando = status === "executando";
  const iniciar = document.getElementById("pm-exec-iniciar");
  iniciar.disabled = executando;
  iniciar.innerHTML = executando ? `<span class="spin">${icon("loader")}</span> Executando…` : `${icon("play")} Iniciar pré-matrícula`;
  const cancelar = document.getElementById("pm-exec-cancelar");
  cancelar.style.display = executando ? "" : "none";
  cancelar.disabled = !!s.cancelando;
  document.getElementById("pm-opt-pular").disabled = executando;
  document.getElementById("pm-opt-debug").disabled = executando;
  _pmDesenharEtapas(s.logs, status);

  const log = document.getElementById("pm-exec-log");
  if (s.logs && s.logs.length) {
    const noFim = log.scrollTop + log.clientHeight >= log.scrollHeight - 8;
    log.style.display = "";
    log.textContent = s.logs.slice(-80).join("\n");
    if (noFim) log.scrollTop = log.scrollHeight;
  }
  const msg = document.getElementById("pm-exec-msg");
  msg.className = "pm-exec-msg" + (status === "erro" ? " erro" : "");
  if (status === "erro") msg.textContent = s.erro ? `Falhou: ${s.erro}` : "A execução terminou com erro (veja o log).";
  else if (status === "concluido") msg.textContent = "Concluído. Os dados abaixo foram atualizados.";
  else if (status === "cancelado") msg.textContent = "Execução cancelada.";
  else msg.textContent = "";
}

function _pmExecPararTimer() {
  if (_pmExecTimer) clearInterval(_pmExecTimer);
  _pmExecTimer = null;
}

async function _pmExecConsultar() {
  const sec = document.getElementById("sec-prematricula");
  if (!sec.classList.contains("active")) { _pmExecPararTimer(); return; }     // saiu da tela: o servidor segue rodando
  let s;
  try { s = await apiGet(`/automacoes/${PM_CHAVE}/status`); } catch (e) { return; }
  _pmExecMostrar(s);
  const anterior = _pmExecUltimoStatus;
  _pmExecUltimoStatus = s.status;
  if (s.status === "executando") return;
  _pmExecPararTimer();
  if (anterior === "executando" && s.status === "concluido") await carregarPreMatricula();   // traz os dados novos
}

function _pmExecIniciarTimer() {
  if (!_pmExecTimer) _pmExecTimer = setInterval(_pmExecConsultar, 2000);
}

/** Ao abrir a tela: se já há uma execução rodando (ex.: iniciada antes de trocar de aba), retoma o painel. */
async function _pmExecSincronizar() {
  let s;
  try { s = await apiGet(`/automacoes/${PM_CHAVE}/status`); } catch (e) { return; }
  _pmExecUltimoStatus = s.status;
  if (s.status === "executando") {
    document.getElementById("pm-exec").style.display = "";
    _pmExecMostrar(s);
    _pmExecIniciarTimer();
  }
}

async function iniciarPreMatricula() {
  const msg = document.getElementById("pm-exec-msg");
  msg.className = "pm-exec-msg";
  msg.textContent = "Iniciando…";
  try {
    await apiPost(`/automacoes/${PM_CHAVE}/executar`, {
      debug: document.getElementById("pm-opt-debug").checked,
      pular_pendentes: document.getElementById("pm-opt-pular").checked,
    });
  } catch (e) {
    msg.className = "pm-exec-msg erro";
    msg.textContent = e.message;
    return;
  }
  document.getElementById("pm-exec-log").textContent = "";
  _pmExecUltimoStatus = "executando";
  await _pmExecConsultar();
  _pmExecIniciarTimer();
}

async function cancelarPreMatricula() {
  const msg = document.getElementById("pm-exec-msg");
  try { await apiPost(`/automacoes/${PM_CHAVE}/cancelar`, {}); }
  catch (e) { msg.className = "pm-exec-msg erro"; msg.textContent = e.message; return; }
  await _pmExecConsultar();
}

function ligarPainelExecucaoPm() {
  const sec = document.getElementById("sec-prematricula");
  if (sec.dataset.execLigado === "1") return;
  sec.dataset.execLigado = "1";
  document.getElementById("pm-btn-executar").addEventListener("click", () => {
    const painel = document.getElementById("pm-exec");
    painel.style.display = painel.style.display === "none" ? "" : "none";
    if (painel.style.display !== "none") _pmExecConsultar();
  });
  document.getElementById("pm-exec-iniciar").addEventListener("click", iniciarPreMatricula);
  document.getElementById("pm-exec-cancelar").addEventListener("click", cancelarPreMatricula);
  _pmDesenharEtapas([], "nunca_executado");
}

async function carregarPreMatricula() {
  const sec = document.getElementById("sec-prematricula");
  ligarAcoesTela("prematricula");
  ligarPainelExecucaoPm();
  _pmExecSincronizar();
  try {
    _pmDados = await apiGet("/prematricula/cadastros");
    const colunas = [{ chave: "nome_aluno", label: "Aluno" }, { chave: "cpf", label: "CPF" }, { chave: "nome_responsavel", label: "Responsável" },
      { chave: "telefone", label: "Telefone" }, { chave: "situacao", label: "Situação" }, { chave: "_turmas", label: "Turma(s) de intenção" }];
    _tabelas.prematricula = { colunas, linhas: _pmDados.cadastros, extra: _pmDados };
    _FILTRO_CUSTOM.prematricula = () => _pmFiltrados().map((c) => ({ ...c, _turmas: c.intencoes.map((i) => `${i.turma}${i.pos ? " #" + i.pos : ""}`).join(" | ") }));
  } catch (e) {
    _pmDados = { cadastros: [] };
    _carregarVazio("pm-tbody", "pm-empty", "pm-empty-msg", "Não foi possível carregar /prematricula/cadastros.");
    console.warn("Pré-matrícula: erro ao carregar", e);
    return;
  }
  desenharExtrasTabela("prematricula", _pmDados);
  const n = _pmDados.contagem || {};
  const rotulos = { geral: `Geral (${_pmDados.total})`, matriculados: `Matriculados (${n.matriculado || 0})`, cancelados: `Cancelados (${n.cancelado || 0})`, pendentes: `Pendentes (${n.pendente || 0})` };
  sec.querySelectorAll("[data-pmtab]").forEach((b) => { b.textContent = rotulos[b.dataset.pmtab]; });
  if (sec.dataset.ligada !== "1") {
    sec.dataset.ligada = "1";
    ligarPilulas(sec, "data-pmtab", pmState, "tab", renderPmRows);
    document.getElementById("pm-search").addEventListener("input", (e) => { pmState.search = e.target.value; pmState.page = 1; renderPmRows(); });
  }
  renderPmRows();
}

/* ---------- Transferidos (mesma tela "Transferidos" do index.html, somente leitura) ---------- */

const transfState = { filter: "todos", search: "", sort: { col: "nome", dir: 1 } };
let _transfDados = null;

const _fmtDataIso = (iso) => (iso ? String(iso).slice(0, 10).split("-").reverse().join("/") : "");

function _chipDoc(rotulo, iso, cor) {
  return iso ? `<span class="badge bg-${cor}" title="${escaparHtml(iso)}">${escaparHtml(rotulo)}: ${escaparHtml(_fmtDataIso(iso))}</span>`
    : `<span class="badge bg-muted" style="opacity:.55">${escaparHtml(rotulo)}: —</span>`;
}

function _transfFiltrados() {
  if (!_transfDados) return [];
  const q = semAcento(transfState.search.trim());
  let dados = _transfDados.transferidos.filter((r) => {
    if (transfState.filter !== "todos" && r.status !== transfState.filter) return false;
    return !q || semAcento(r.nome).includes(q) || r.cgm.includes(q) || semAcento(r.turma).includes(q);
  });
  const { col, dir } = transfState.sort;
  return dados.sort((a, b) => (col === "status" ? (a.feitos - b.feitos) * dir
    : semAcento(a[col]).localeCompare(semAcento(b[col]), "pt-BR") * dir));
}

function renderTransfRows() {
  const dados = _transfFiltrados();
  if (!dados.length) {
    _carregarVazio("transf-tbody", "transf-empty", "transf-empty-msg", _transfDados.transferidos.length ? "Nenhum resultado."
      : 'Nenhum aluno transferido registrado. Use "Atualizar dados" para rodar a automação.');
    return;
  }
  document.getElementById("transf-empty").style.display = "none";
  document.getElementById("transf-tbody").innerHTML = dados.map((r) => {
    const g = r.guia, h = r.historico, p = r.parecer;
    const st = r.status === "completo" ? badge("Completo", "bg-lime") : r.status === "pendente" ? badge("Pendente", "bg-rose") : badge(`${r.feitos}/${r.total_passos}`, "bg-amber");
    return `<tr>
      <td class="td-name">${escaparHtml(r.nome)}<small>${escaparHtml(r.turma || "—")}</small></td>
      <td class="td-mono">${escaparHtml(r.cgm)}</td>
      <td>${_chipDoc("Emitida", g.emitido_em, "cyan")} ${_chipDoc("Secr.", g.assinado_secretario, "blue")} ${_chipDoc("Dir.", g.assinado_diretor, "lime")}</td>
      <td>${_chipDoc("Emitido", h.emitido_em, "cyan")} ${_chipDoc("Secr.", h.assinado_secretario, "blue")} ${_chipDoc("Dir.", h.assinado_diretor, "lime")}</td>
      <td>${_chipDoc("Digitalizado", p.digitalizado_em, "blue")} ${_chipDoc("Anexado", p.anexado_em, "lime")}</td>
      <td>${st}</td>
    </tr>`;
  }).join("");
}

async function carregarTransferidos() {
  const sec = document.getElementById("sec-transferidos");
  ligarAcoesTela("transferidos");
  try {
    _transfDados = await apiGet("/transferidos/lista");
    const colunas = [{ chave: "nome", label: "Aluno" }, { chave: "cgm", label: "CGM" }, { chave: "turma", label: "Turma" },
      { chave: "guia_emitida", label: "Guia emitida" }, { chave: "guia_secretario", label: "Guia assinada (secretário)" }, { chave: "guia_diretor", label: "Guia assinada (diretor)" },
      { chave: "hist_emitido", label: "Histórico emitido" }, { chave: "hist_secretario", label: "Histórico assinado (secretário)" }, { chave: "hist_diretor", label: "Histórico assinado (diretor)" },
      { chave: "parecer_digitalizado", label: "Parecer digitalizado" }, { chave: "parecer_anexado", label: "Parecer anexado" }, { chave: "status", label: "Status" }];
    const plano = (r) => ({
      nome: r.nome, cgm: r.cgm, turma: r.turma,
      guia_emitida: _fmtDataIso(r.guia.emitido_em), guia_secretario: _fmtDataIso(r.guia.assinado_secretario), guia_diretor: _fmtDataIso(r.guia.assinado_diretor),
      hist_emitido: _fmtDataIso(r.historico.emitido_em), hist_secretario: _fmtDataIso(r.historico.assinado_secretario), hist_diretor: _fmtDataIso(r.historico.assinado_diretor),
      parecer_digitalizado: _fmtDataIso(r.parecer.digitalizado_em), parecer_anexado: _fmtDataIso(r.parecer.anexado_em),
      status: r.status === "completo" ? "Completo" : r.status === "pendente" ? "Pendente" : `${r.feitos}/${r.total_passos}`,
    });
    _tabelas.transferidos = { colunas, linhas: _transfDados.transferidos.map(plano), extra: _transfDados };
    _FILTRO_CUSTOM.transferidos = () => _transfFiltrados().map(plano);
  } catch (e) {
    _transfDados = { transferidos: [] };
    _carregarVazio("transf-tbody", "transf-empty", "transf-empty-msg", "Não foi possível carregar /transferidos/lista.");
    console.warn("Transferidos: erro ao carregar", e);
    return;
  }
  desenharExtrasTabela("transferidos", _transfDados);
  const n = _transfDados.contagem || {};
  const rotulos = { todos: `Todos (${_transfDados.total})`, completo: `Completos (${n.completo || 0})`, parcial: `Parciais (${n.parcial || 0})`, pendente: `Pendentes (${n.pendente || 0})` };
  sec.querySelectorAll("[data-tf]").forEach((b) => { b.textContent = rotulos[b.dataset.tf]; });
  if (sec.dataset.ligada !== "1") {
    sec.dataset.ligada = "1";
    ligarPilulas(sec, "data-tf", transfState, "filter", renderTransfRows);
    ligarOrdenacao(sec, "data-ts", transfState, renderTransfRows);
    document.getElementById("transf-q").addEventListener("input", (e) => { transfState.search = e.target.value; renderTransfRows(); });
  }
  renderTransfRows();
}

/* ---------- Automações ---------- */

const ICONES_AUTOMACAO = {
  funcionarios: "badge",
  vinculos: "compare",
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
  parecer_planilha: "certificate",
  pareceres_digitalizados: "certificate",
  transferidos_fila: "transfer",
  transferidos_gerar: "transfer",
  pareceres_transferidos: "certificate",
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
// Campos das automações AINDA NÃO IMPLEMENTADAS (o servidor responde 501). As implementadas montam a
// tela a partir do registro (src/comum/registro_scripts.py) via GET /automacoes/<chave>/componentes.
const CAMPOS_AUTOMACAO = {
  agendador: [
    { tipo: "select", id: "frequencia", label: "Frequência", opcoes: [
      { valor: "diaria", texto: "Diária" },
      { valor: "semanal", texto: "Semanal" },
      { valor: "mensal", texto: "Mensal" },
    ] },
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
  abrirSubgrupoDaAutomacao(chave);
  ligarControlesExecucao();
  _execResetar();
  carregarFlagsAutomacao(chave);
  sincronizarExecucao(chave);
}

/** Monta o HTML de um campo do formulário conforme seu tipo. */
function campoHTML(campo) {
  // campo condicional: só aparece quando outro campo tem certo valor (ver atualizarCamposDinamicos)
  const cond = campo.visivelSe ? ` data-visivel-se="${campo.visivelSe.campo}=${campo.visivelSe.valor}"` : "";
  const nome = ` data-nome="${campo.nome || campo.id || ""}"`;
  if (campo.tipo === "caixa") {
    return `
      <div class="field"${cond}>
        <label style="display:flex; gap:10px; align-items:flex-start; cursor:pointer;">
          <input type="checkbox" id="${campo.id}"${nome} ${campo.padrao ? "checked" : ""} style="margin-top:3px;">
          <span>${campo.label}${campo.descricao ? `<div class="campo-ajuda">${campo.descricao}</div>` : ""}</span>
        </label>
      </div>`;
  }
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
  if (campo.tipo === "texto" && campo.multilinha) {
    return `
      <div class="field"${cond}>
        <label>${campo.label}</label>
        <textarea id="${campo.id}"${nome} rows="${campo.linhas || 9}" placeholder="${campo.placeholder || ""}">${String(campo.padrao || "").replace(/&/g, "&amp;").replace(/</g, "&lt;")}</textarea>
      </div>`;
  }
  if (campo.tipo === "texto") {
    return `
      <div class="field"${cond}>
        <label>${campo.label}</label>
        <input type="text" id="${campo.id}"${nome} placeholder="${campo.placeholder || ""}"${campo.padrao ? ` value="${String(campo.padrao).replace(/"/g, "&quot;")}"` : ""}>
      </div>`;
  }
  if (campo.tipo === "select") {
    const vazio = campo.semVazio ? "" : '<option value="">Selecione...</option>';
    const temAjuda = (campo.opcoes || []).some((o) => o.ajuda);
    return `
      <div class="field"${cond}>
        <label>${campo.label}</label>
        <select id="${campo.id}"${nome}>
          ${vazio}
          ${(campo.opcoes || []).map((o) => `<option value="${o.valor}"${o.valor === campo.padrao ? " selected" : ""}>${o.texto}</option>`).join("")}
        </select>
        ${temAjuda ? `<div class="campo-ajuda" id="${campo.id}-ajuda"></div>` : ""}
      </div>`;
  }
  return "";
}

let _infoComponentes = null;       // dados dos componentes do script aberto (null = automação no modo antigo)
let _timerPrevia = null;

/** Monta a tela da automação: componentes compartilhados (se o script está no registro) ou os campos próprios. */
async function renderizarCamposAutomacao(chave) {
  const container = document.getElementById("campos-automacao");
  _infoComponentes = null;
  clearTimeout(_timerPrevia);
  container.innerHTML = '<p style="color:var(--txt3); font-size:13px; margin-bottom:16px;">Carregando opções…</p>';
  let info = { registrado: false };
  try {
    info = await apiGet(`/automacoes/${chave}/componentes`);
  } catch (e) { /* sem o endpoint: segue com os campos antigos */ }
  if (chave !== automacaoAtual) return;           // o usuário já abriu outra automação
  if (info.registrado) {
    _infoComponentes = info;
    montarComponentesCompartilhados(container, chave, info);
  } else {
    renderizarCamposAntigos(chave, container);
  }
}

function renderizarCamposAntigos(chave, container) {
  const campos = CAMPOS_AUTOMACAO[chave] ?? CAMPOS_PADRAO;

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

  container.querySelectorAll("select, input[type=checkbox]").forEach((s) => s.addEventListener("change", atualizarCamposDinamicos));
  atualizarCamposDinamicos();
}

/* ---------- Componentes compartilhados (turma, situação, CGM, teste, erros, debug) ---------- */
/* Os mesmos de todos os scripts registrados em src/comum/registro_scripts.py. O que cada um
   significa e como vira argumento de linha de comando está em src/comum/opcoes_execucao.py. */

function _compTurmaHTML(info) {
  if (!info.tem_turmas) {
    return `<div class="field"><label>Turma</label>
      <div class="campo-ajuda" style="color:var(--amber)">Ainda não há turmas.json: execute primeiro a automação <b>Turmas</b>.</div></div>`;
  }
  const grupos = info.turmas || [];
  const porAno = grupos.filter((g) => g.turmas.length > 1)
    .map((g) => `<option value="g:${escaparHtml(g.rotulo)}">${escaparHtml(g.rotulo)} (todas as turmas)</option>`).join("");
  const especificas = grupos.flatMap((g) => g.turmas)
    .map((t) => `<option value="t:${escaparHtml(t)}">${escaparHtml(t)}</option>`).join("");
  return `
    <div class="field">
      <label>Turma</label>
      <select id="comp-turma">
        <option value="">Todas as turmas</option>
        ${porAno ? `<optgroup label="Por ano">${porAno}</optgroup>` : ""}
        <optgroup label="Turma específica">${especificas}</optgroup>
      </select>
    </div>`;
}

function _compCaixaHTML(id, label, descricao) {
  return `
    <div class="field">
      <label class="comp-check"><input type="checkbox" id="${id}">
        <span>${label}${descricao ? `<div class="campo-ajuda">${escaparHtml(descricao)}</div>` : ""}</span></label>
    </div>`;
}

function montarComponentesCompartilhados(container, chave, info) {
  const r = new Set(info.recursos);
  const partes = [];
  if (r.has("turma")) partes.push(_compTurmaHTML(info));
  if (r.has("situacao")) {
    partes.push(`
      <div class="field">
        <label>Processar</label>
        <label class="comp-check"><input type="checkbox" id="comp-matriculados" checked> Matriculados</label>
        <label class="comp-check"><input type="checkbox" id="comp-transferidos"> Transferidos</label>
      </div>`);
  }
  if (r.has("cgm")) {
    partes.push(`
      <div class="field">
        <label>${info.cgm_obrigatorio ? "CGMs" : "CGMs (opcional)"}</label>
        ${info.cgm_obrigatorio ? "" : '<div class="campo-ajuda" style="margin:-2px 0 6px">Se preencher, só estes alunos são processados e turma/situação são ignoradas.</div>'}
        <textarea id="comp-cgm" rows="5" spellcheck="false"
          placeholder="Um por linha, ou separados por vírgula ou ponto e vírgula:&#10;1234567890&#10;1234567891, 1234567892; 1234567893"></textarea>
        <div class="campo-ajuda" id="comp-cgm-previa"></div>
      </div>`);
  }
  if (r.has("erros")) {
    partes.push(_compCaixaHTML("comp-erros", "Reprocessar só o que deu erro",
      "Refaz apenas o que falhou na última execução. " + (r.has("situacao") ? "Quando marcado, turma e situação são ignoradas." : "")));
  }
  (info.extras || []).forEach((campo) => partes.push(campoHTML(campo)));
  if (r.has("debug")) partes.push(_compCaixaHTML("comp-debug", "Modo debug (análise)", info.ajuda_debug));
  if (r.has("teste")) partes.push(_compCaixaHTML("comp-teste", "Modo de teste", info.ajuda_teste));
  if (!partes.length) {
    partes.push('<p style="color:var(--txt3); font-size:13px; margin-bottom:16px;">Esta automação não precisa de parâmetros adicionais — clique em Executar tarefa.</p>');
  }
  partes.push('<div class="comp-previa" id="comp-previa"></div>');

  container.innerHTML = partes.join("");
  const btnPasta = document.getElementById("btn-escolher-pasta");
  if (btnPasta) btnPasta.addEventListener("click", () => abrirSeletorDePasta(btnPasta));
  container.querySelectorAll("select, input[type=checkbox]").forEach((sel) => sel.addEventListener("change", atualizarCamposDinamicos));
  atualizarCamposDinamicos();
  container.querySelectorAll("[id^='comp-'], .field select, .field input[type=checkbox]").forEach((el) => {
    el.addEventListener(el.tagName === "TEXTAREA" ? "input" : "change", () => agendarPrevia());
  });
  agendarPrevia(true);
}

/** Lê as escolhas dos componentes para o JSON que a rota espera. */
function coletarComponentes(payload) {
  const v = (id) => document.getElementById(id);
  const info = _infoComponentes;
  if (!info) return payload;
  const r = new Set(info.recursos);
  if (r.has("turma")) {
    const escolha = v("comp-turma")?.value || "";
    if (escolha.startsWith("g:")) {
      payload.turmas = (info.turmas.find((g) => g.rotulo === escolha.slice(2)) || { turmas: [] }).turmas;
    } else if (escolha.startsWith("t:")) {
      payload.turmas = [escolha.slice(2)];
    } else {
      payload.turmas = [];                       // vazio = todas
    }
  }
  if (r.has("situacao")) {
    payload.matriculados = !!v("comp-matriculados")?.checked;
    payload.transferidos = !!v("comp-transferidos")?.checked;
  }
  if (r.has("cgm")) payload.cgms_texto = v("comp-cgm")?.value || "";
  if (r.has("erros")) payload.erros = !!v("comp-erros")?.checked;
  if (r.has("debug")) payload.debug = !!v("comp-debug")?.checked;
  if (r.has("teste")) payload.modo_teste = !!v("comp-teste")?.checked;
  return payload;
}

function agendarPrevia(imediato = false) {
  clearTimeout(_timerPrevia);
  _timerPrevia = setTimeout(atualizarPrevia, imediato ? 0 : 350);
}

/** "O que será processado": conta quem seria afetado com as escolhas atuais, sem executar nada. */
async function atualizarPrevia() {
  const chave = automacaoAtual;
  const info = _infoComponentes;
  const alvo = document.getElementById("comp-previa");
  if (!info || !alvo) return;
  const payload = _execMontarPayload();

  if (info.recursos.includes("cgm")) {
    const caixa = document.getElementById("comp-cgm-previa");
    try {
      const r = await apiPost("/cgm/analisar", { texto: payload.cgms_texto || "" });
      if (caixa && chave === automacaoAtual) {
        caixa.textContent = (payload.cgms_texto || "").trim() ? r.texto : "";
        caixa.style.color = r.invalidos.length ? "var(--amber)" : "";
      }
    } catch (e) { /* sem conferência ao vivo */ }
  }

  try {
    const r = await apiPost(`/automacoes/${chave}/previa`, payload);
    if (chave !== automacaoAtual) return;
    alvo.classList.remove("aviso");
    alvo.textContent = r.texto ? `Prévia: ${r.texto}` : "";
    alvo.dataset.texto = r.texto || "";
  } catch (e) {
    if (chave !== automacaoAtual) return;
    alvo.classList.add("aviso");
    alvo.textContent = e.message;
    alvo.dataset.texto = "";
  }
}

/** Pede confirmação (com a prévia) antes de scripts que alteram algo no SERE. Resolve true/false. */
function confirmarExecucao(info, previa) {
  return new Promise((resolve) => {
    abrirModal("Confirmar execução", (corpo, fechar) => {
      corpo.innerHTML = `
        <p class="conf-aviso" style="font-weight:600; margin-bottom:10px"></p>
        <p class="conf-previa" style="margin-bottom:10px"></p>
        ${info.recursos.includes("teste") ? '<p class="campo-ajuda">Dica: marque <b>Modo de teste</b> para processar só o primeiro antes de rodar tudo.</p>' : ""}
        <div class="modal-acoes">
          <button class="btn-sm" id="conf-nao" style="padding:9px 16px;font-size:.78rem">Cancelar</button>
          <button class="btn-primary" id="conf-sim">Confirmar e executar</button>
        </div>`;
      corpo.querySelector(".conf-aviso").textContent = info.aviso_confirmacao || "Esta automação altera dados no SERE.";
      corpo.querySelector(".conf-previa").textContent = previa || "";
      corpo.querySelector("#conf-sim").addEventListener("click", () => { resolve(true); fechar(); });
      corpo.querySelector("#conf-nao").addEventListener("click", fechar);
    }, () => resolve(false));       // Esc/Cancelar; ignorado se já resolveu com true
  });
}

/** Texto de ajuda de cada opção escolhida e campos que só aparecem para certo valor de outro campo. */
function atualizarCamposDinamicos() {
  const campos = _infoComponentes?.extras ?? CAMPOS_AUTOMACAO[automacaoAtual] ?? [];
  document.querySelectorAll("#campos-automacao select").forEach((sel) => {
    const ajuda = document.getElementById(`${sel.id}-ajuda`);
    if (!ajuda) return;
    const campo = campos.find((c) => c.id === sel.id);
    ajuda.textContent = campo?.opcoes?.find((o) => o.valor === sel.value)?.ajuda || "";
  });
  document.querySelectorAll("#campos-automacao [data-visivel-se]").forEach((el) => {
    const [id, valor] = el.dataset.visivelSe.split("=");
    const alvo = document.getElementById(id);
    const atual = alvo?.type === "checkbox" ? String(alvo.checked) : alvo?.value;     // caixa de marcar: "true"/"false"
    el.style.display = valor.split("|").includes(atual) ? "" : "none";   // "a|b" = vale para a ou b
  });
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
    btn.disabled = emConsulta();
    btn.style.background = "";
    btn.style.borderColor = "";
    btn.style.color = "";
    btn.innerHTML = btn.dataset.rotuloOriginal;
    if (emConsulta()) { btn.title = "Somente consulta: não é possível executar automações neste ano."; btn.dataset.tituloConsulta = "1"; }
    else if (btn.dataset.tituloConsulta) { btn.removeAttribute("title"); delete btn.dataset.tituloConsulta; }
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

/* Perguntas que a automação faz no meio da execução (ex.: código de verificação do RCO).
   O servidor devolve a pergunta em /status ("pergunta"); a resposta vai em /resposta. */
let _perguntaAbertaId = null;
let _perguntaAdiarAte = 0;

function _execPerguntar(chave, pergunta) {
  if (!pergunta) { _perguntaAbertaId = null; return; }
  if (pergunta.id === _perguntaAbertaId || Date.now() < _perguntaAdiarAte) return;
  _perguntaAbertaId = pergunta.id;
  let respondida = false;

  abrirModal(pergunta.titulo || "A automação precisa de uma informação", (corpo, fechar) => {
    corpo.innerHTML = `
      <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">${escaparHtml(pergunta.mensagem || "")}</p>
      <div class="field"><label>${escaparHtml(pergunta.rotulo || "Resposta")}</label>
        <input type="${pergunta.segredo ? "password" : "text"}" id="mdl-pergunta-valor" autocomplete="one-time-code"></div>
      <div id="mdl-pergunta-erro" style="color:var(--rose); font-size:.78rem; min-height:1.1em; margin-bottom:8px;"></div>
      <div class="modal-acoes">
        <button class="btn-sm" id="mdl-pergunta-cancelar" style="padding:9px 16px;font-size:.78rem">Cancelar execução</button>
        <button class="btn-primary" id="mdl-pergunta-ok">Enviar</button>
      </div>`;
    const campo = corpo.querySelector("#mdl-pergunta-valor");
    const erro = corpo.querySelector("#mdl-pergunta-erro");
    const btnOk = corpo.querySelector("#mdl-pergunta-ok");

    const enviar = async () => {
      const valor = campo.value.trim();
      if (!valor) { erro.textContent = "Digite a resposta antes de enviar."; return; }
      btnOk.disabled = true;
      erro.textContent = "";
      try {
        await apiPost(`/automacoes/${chave}/resposta`, { id: pergunta.id, valor });
        respondida = true;
        fechar();
        toast("Resposta enviada");
      } catch (e) {
        erro.textContent = e.message;     // ex.: código fora do formato — dá para tentar de novo
        btnOk.disabled = false;
        campo.focus();
      }
    };
    btnOk.addEventListener("click", enviar);
    campo.addEventListener("keydown", (e) => { if (e.key === "Enter") enviar(); });
    corpo.querySelector("#mdl-pergunta-cancelar").addEventListener("click", async () => {
      respondida = true;                  // não reabrir
      fechar();
      try { await apiPost(`/automacoes/${chave}/cancelar`, {}); toast("Cancelamento solicitado…"); } catch (e) { toast(e.message); }
    });
  }, () => {
    // Fechou sem responder (Esc): a pergunta continua valendo no servidor; reabre daqui a pouco.
    if (!respondida) { _perguntaAbertaId = null; _perguntaAdiarAte = Date.now() + 8000; }
  });
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
    _execPerguntar(chave, s.pergunta);
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

  // Qualquer outro campo dinâmico (texto/select) pelo id — ou pelo data-nome, quando o id é só da tela
  document.querySelectorAll("#campos-automacao input[type=text], #campos-automacao textarea, #campos-automacao select").forEach((el) => {
    if (el.id && el.id !== "select-turmas" && !el.id.startsWith("comp-")) payload[el.dataset.nome || el.id] = el.value;
  });
  // Caixas de marcar (as da lista de turmas não têm id e já vão em payload.turmas)
  document.querySelectorAll("#campos-automacao input[type=checkbox][id]").forEach((el) => {
    if (!el.id.startsWith("comp-")) payload[el.dataset.nome || el.id] = el.checked;
  });
  return coletarComponentes(payload);
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

  if (_infoComponentes) {
    // Prévia fresca (o usuário pode ter acabado de digitar). Se há erro de preenchimento, mostra e não prossegue.
    clearTimeout(_timerPrevia);
    await atualizarPrevia();
    const alvo = document.getElementById("comp-previa");
    if (alvo?.classList.contains("aviso") && alvo.textContent) { toast(alvo.textContent); return; }
  }
  const payload = _execMontarPayload();
  if (_infoComponentes?.confirmar && !payload.modo_teste) {
    const previa = document.getElementById("comp-previa")?.dataset.texto || "";
    if (!(await confirmarExecucao(_infoComponentes, previa))) return;
  }

  _execEstadoBotao("executando");
  document.getElementById("exec-log")?.remove();
  try {
    await apiPost(`/automacoes/${chave}/executar`, payload);
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
  ano_letivo: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Ano letivo</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Escolha o ano de trabalho, volte a um ano anterior ou restaure os dados de um ano. Os dados de cada ano ficam em <code>dados/&lt;ano&gt;/</code>. <b>A troca é imediata</b>: ao escolher um ano, as telas e as automações passam a usar os dados dele, sem reiniciar o programa. Só não dá para trocar enquanto uma automação estiver em execução.</p>
    <div id="cfg-ano-aviso"></div>
    <div id="cfg-ano-status" style="font-family:var(--mono); font-size:.74rem; color:var(--txt3); margin-bottom:10px;">Carregando…</div>
    <div id="cfg-ano-anos" style="margin-bottom:16px;"></div>
    <div class="field"><label>Voltar os dados de um ano (a partir de um backup)</label>
      <select id="cfg-ano-backup"></select>
      <label style="display:flex; gap:8px; align-items:center; font-size:.78rem; margin-top:8px; cursor:pointer;"><input type="checkbox" id="cfg-ano-sodados" checked> Só os dados do ano (não mexe na configuração nem no calendário)</label>
      <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
        <button class="btn-sm" id="cfg-ano-conferir" style="padding:9px 16px;font-size:.78rem">Conferir (não altera nada)</button>
        <button class="btn-primary" id="cfg-ano-restaurar">Restaurar os dados…</button>
      </div>
    </div>
    <div class="field"><label>Dados fictícios para teste</label>
      <div style="display:flex; gap:8px; align-items:center;">
        <input type="text" id="cfg-ano-ficticio" value="2025" maxlength="4" style="max-width:100px;">
        <button class="btn-sm" id="cfg-ano-gerar" style="padding:9px 16px;font-size:.78rem">Criar dados fictícios</button>
      </div>
      <div style="color:var(--txt3); font-size:.72rem; margin-top:6px;">Cria turmas, alunos, funcionários e pré-matrícula inventados num ano que não está em uso (e um backup dele, para testar a restauração). Nunca escreve por cima de dados de verdade.</div>
    </div>
    <div id="cfg-ano-msg" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); white-space:pre-wrap;"></div>`,
  senha_sere: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do SERE</h4>
    <div class="field"><label>Usuário</label><input type="text" id="cfg-sere-usuario" placeholder="usuário do SERE"></div>
    <div class="field"><label>Senha</label><input type="password" id="cfg-sere-senha" placeholder="••••••••"></div>
    <button class="btn-primary" id="cfg-sere-salvar">Salvar credenciais</button>`,
  escola: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Dados da escola</h4>
    <div id="cfg-escola-form"></div>`,
  data_corte_transferidos: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Data de corte dos transferidos</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">O processo automático de transferidos vale para quem foi transferido <b>a partir</b> desta data (inclusive). Antes dela, a guia e o histórico são considerados já tratados à mão e não são refeitos. Quem foi transferido e voltou à escola também não é refeito.</p>
    <div class="field"><label>Data de corte (dd/mm/aaaa)</label><input type="text" id="cfg-corte-data" placeholder="22/06/2026"></div>
    <div id="cfg-corte-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:14px;">Carregando…</div>
    <div style="display:flex; gap:10px; flex-wrap:wrap;">
      <button class="btn-primary" id="cfg-corte-salvar">Salvar data</button>
      <button class="btn-sm" id="cfg-corte-padrao" style="padding:9px 16px;font-size:.78rem">Usar a data padrão</button>
    </div>`,
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
  modelos_parecer: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Modelos de parecer (Fundamental)</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Envie o modelo Word (.docx) e marque as turmas que o usam. O modelo precisa ter <code>$ALUNO</code>; também valem <code>$ESCOLA</code>, <code>$TURMA</code>, <code>$ANO</code>, <code>$CGM</code> e <code>$CHAMADA</code>. Reenviar um arquivo com o mesmo nome substitui o modelo de todas as turmas ligadas a ele.</p>
    <div class="field"><label>Arquivo do modelo (.docx)</label><input type="file" id="cfg-mp-arquivo" accept=".docx"></div>
    <div class="field"><label>Turmas que usam este modelo</label>
      <div id="cfg-mp-turmas" style="max-height:220px; overflow:auto; border:1px solid var(--border); border-radius:8px; padding:8px 10px; font-size:.8rem;">Carregando…</div>
    </div>
    <div id="cfg-mp-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:14px;"></div>
    <button class="btn-primary" id="cfg-mp-enviar">Enviar modelo</button>`,
  senha_prematricula: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha da Pré-matrícula</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Login e senha do portal da pré-matrícula (diferentes dos do SERE). Ficam em <code>credenciais/.env</code> neste computador.</p>
    <div class="field"><label>Login (matrícula)</label><input type="text" id="cfg-prem-login" placeholder="login da pré-matrícula" autocomplete="off"></div>
    <div class="field"><label>Senha</label><input type="password" id="cfg-prem-senha" placeholder="••••••••" autocomplete="new-password"></div>
    <div id="cfg-prem-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:14px;">Carregando…</div>
    <button class="btn-primary" id="cfg-prem-salvar">Salvar credenciais</button>`,
  senha_rco: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do RCO</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">O RCO entra pela mesma Central de Segurança do SERE, então normalmente o login e a senha são os mesmos. Fica em <code>credenciais/.env</code> neste computador.</p>
    <label style="display:flex; align-items:center; gap:8px; font-size:.82rem; margin-bottom:14px; cursor:pointer;"><input type="checkbox" id="cfg-rco-mesmas" checked> Usar o mesmo login e senha do SERE</label>
    <div id="cfg-rco-campos" style="display:none;">
      <div class="field"><label>Login (CPF ou Login Sentinela)</label><input type="text" id="cfg-rco-login" placeholder="CPF ou Login Sentinela" autocomplete="off"></div>
      <div class="field"><label>Senha</label><input type="password" id="cfg-rco-senha" placeholder="••••••••" autocomplete="new-password"></div>
    </div>
    <div id="cfg-rco-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:14px;">Carregando…</div>
    <button class="btn-primary" id="cfg-rco-salvar">Salvar credenciais do RCO</button>`,
  chave_gmail: `
    <h4 style="margin-bottom:14px; font-size:.9rem;">Salvar senha do Gmail</h4>
    <p style="color:var(--txt3); font-size:.82rem; margin-bottom:12px;">Use a <b>senha de app</b> do Google (16 letras, no formato <code>btxq xxxx xxxx xxxx</code>), não a senha normal da conta. Fica em <code>credenciais/.env</code> neste computador.</p>
    <div class="field"><label>E-mail (Gmail)</label><input type="email" id="cfg-gmail-email" placeholder="seu.email@gmail.com" autocomplete="off"></div>
    <div class="field"><label>Senha de app</label><input type="password" id="cfg-gmail-senha" placeholder="xxxx xxxx xxxx xxxx" autocomplete="new-password" maxlength="40"></div>
    <div id="cfg-gmail-status" style="font-family:var(--mono); font-size:.72rem; color:var(--txt3); margin-bottom:14px;">Carregando…</div>
    <button class="btn-primary" id="cfg-gmail-salvar">Salvar senha do Gmail</button>`,
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
      if (row.dataset.config === "ano_letivo") {
        conectarFormAnoLetivo();
      }
      if (row.dataset.config === "modelos_parecer") {
        conectarFormModelosParecer();
      }
      if (row.dataset.config === "senha_rco") {
        conectarFormRco();
      }
      if (row.dataset.config === "chave_gmail") {
        conectarFormGmail();
      }
      if (row.dataset.config === "senha_prematricula") {
        conectarFormSenhaPrematricula();
      }
      if (row.dataset.config === "pasta_digitalizacao") {
        conectarFormPastaDigitalizacao();
      }
      if (row.dataset.config === "data_corte_transferidos") {
        conectarFormDataCorte();
      }
      if (row.dataset.config === "escola") {
        montarFormEscola(document.getElementById("cfg-escola-form"), {});
      }
    });
  });
}

async function conectarFormDataCorte() {
  const input = document.getElementById("cfg-corte-data");
  const status = document.getElementById("cfg-corte-status");
  const btnSalvar = document.getElementById("cfg-corte-salvar");
  const btnPadrao = document.getElementById("cfg-corte-padrao");
  if (!input || !status || !btnSalvar || !btnPadrao) return;

  const mostrar = (d) => {
    input.value = d.data_corte || "";
    status.innerHTML = d.personalizada
      ? '<span style="color:var(--lime)">✓ Data personalizada em uso</span>'
      : '<span style="color:var(--amber)">Usando a data padrão (' + d.padrao + ') — defina a sua</span>';
  };
  const enviar = async (corpo, botao, textoEspera) => {
    const original = botao.textContent;
    btnSalvar.disabled = btnPadrao.disabled = true;
    botao.textContent = textoEspera;
    try {
      const resp = await apiPost("/configuracoes/data-corte", corpo);
      mostrar(resp);
      toast(resp.mensagem || "Data salva");
    } catch (e) {
      toast(e.message);
    } finally {
      btnSalvar.disabled = btnPadrao.disabled = false;
      botao.textContent = original;
    }
  };

  try {
    mostrar(await apiGet("/configuracoes/data-corte"));
  } catch (e) {
    status.textContent = "Não foi possível ler a configuração atual.";
  }
  btnSalvar.addEventListener("click", () => {
    const data_corte = input.value.trim();
    if (!data_corte) { toast("Informe a data de corte (dd/mm/aaaa)"); return; }
    enviar({ data_corte }, btnSalvar, "Salvando...");
  });
  btnPadrao.addEventListener("click", () => enviar({ usar_padrao: true }, btnPadrao, "Aplicando..."));
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

async function conectarFormRco() {
  const chk = document.getElementById("cfg-rco-mesmas");
  const campos = document.getElementById("cfg-rco-campos");
  const inLogin = document.getElementById("cfg-rco-login");
  const inSenha = document.getElementById("cfg-rco-senha");
  const status = document.getElementById("cfg-rco-status");
  const btn = document.getElementById("cfg-rco-salvar");
  if (!chk || !campos || !inLogin || !inSenha || !status || !btn) return;

  let senhaPropriaSalva = false;
  const alternar = () => { campos.style.display = chk.checked ? "none" : "block"; };
  chk.addEventListener("change", alternar);

  const mostrar = (d) => {
    senhaPropriaSalva = !!d.senha_salva;
    chk.checked = !!d.usa_sere;
    alternar();
    if (d.login) inLogin.value = d.login;
    inSenha.placeholder = senhaPropriaSalva ? "•••••••• (salva — deixe vazio para manter)" : "••••••••";
    if (d.usa_sere) {
      status.textContent = d.sere_configurado
        ? "✓ Usando o login e a senha do SERE."
        : "Usando o SERE, mas as credenciais do SERE ainda não foram salvas.";
    } else {
      status.textContent = d.configurada ? "✓ Credenciais próprias do RCO configuradas." : "Credenciais do RCO incompletas.";
    }
  };
  try {
    mostrar(await apiGet("/configuracoes/rco"));
  } catch (e) {
    status.textContent = "Não foi possível ler a configuração atual.";
  }

  btn.addEventListener("click", async () => {
    let corpo;
    if (chk.checked) {
      corpo = { mesmas_do_sere: true };
    } else {
      const login = inLogin.value.trim();
      const senha = inSenha.value;
      if (!login) { toast("Informe o login do RCO"); return; }
      if (!senha && !senhaPropriaSalva) { toast("Informe a senha do RCO"); return; }
      corpo = { login, senha };
    }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Salvando...";
    try {
      const r = await apiPost("/configuracoes/rco", corpo);
      inSenha.value = "";
      mostrar(r);
      toast(r.mensagem || "Credenciais salvas");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
}

async function conectarFormGmail() {
  const inEmail = document.getElementById("cfg-gmail-email");
  const inSenha = document.getElementById("cfg-gmail-senha");
  const status = document.getElementById("cfg-gmail-status");
  const btn = document.getElementById("cfg-gmail-salvar");
  if (!inEmail || !inSenha || !status || !btn) return;

  // Enquanto digita (ou cola), agrupa em "xxxx xxxx xxxx xxxx".
  inSenha.addEventListener("input", () => {
    const limpo = inSenha.value.replace(/\s+/g, "").slice(0, 16);
    inSenha.value = limpo.replace(/(.{4})(?=.)/g, "$1 ");
  });

  let senhaSalva = false;
  const mostrar = (d) => {
    senhaSalva = !!d.senha_salva;
    if (d.email) inEmail.value = d.email;
    inSenha.placeholder = senhaSalva ? "•••• •••• •••• •••• (salva — deixe vazio para manter)" : "xxxx xxxx xxxx xxxx";
    status.textContent = d.configurada ? "✓ Credenciais configuradas." : "Credenciais ainda não configuradas.";
  };
  try {
    mostrar(await apiGet("/configuracoes/gmail"));
  } catch (e) {
    status.textContent = "Não foi possível ler a configuração atual.";
  }

  btn.addEventListener("click", async () => {
    const email = inEmail.value.trim();
    const senha = inSenha.value;
    if (!email) { toast("Informe o e-mail do Gmail"); return; }
    if (!senha && !senhaSalva) { toast("Informe a senha de app do Gmail"); return; }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Salvando...";
    try {
      const r = await apiPost("/configuracoes/gmail", { email, senha });
      inSenha.value = "";
      mostrar(r);
      toast(r.mensagem || "Credenciais salvas");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
}

async function conectarFormAnoLetivo() {
  const el = (id) => document.getElementById(id);
  const status = el("cfg-ano-status"), caixaAnos = el("cfg-ano-anos"), selBackup = el("cfg-ano-backup");
  const aviso = el("cfg-ano-aviso"), msg = el("cfg-ano-msg"), inFict = el("cfg-ano-ficticio");
  if (!status || !caixaAnos || !selBackup || !aviso || !msg || !inFict) return;
  const BASE = "/configuracoes/ano-letivo";
  let estado = null;

  const mostrar = (texto) => { msg.textContent = texto || ""; if (texto) toast(texto); };

  const desenhar = (d) => {
    estado = d;
    status.textContent = `Em uso agora: ${d.ativo}  ·  No próximo início: ${d.proximo}${d.automatico ? " (automático = ano do calendário)" : ""}`;
    aviso.innerHTML = d.fixado_por_ambiente
      ? `<div style="color:var(--amber); font-size:.8rem; margin-bottom:10px;">⚠ O ano está fixado pela variável de ambiente <code>AUTO_SERE_ANO_BASE</code>: ela manda sobre esta tela.</div>`
      : d.pendente_reinicio
        ? `<div style="color:var(--amber); font-size:.8rem; margin-bottom:10px;">⚠ A configuração aponta para <b>${escaparHtml(d.proximo)}</b>, mas o programa está em ${escaparHtml(d.ativo)}. Clique em “Usar este ano” em ${escaparHtml(d.proximo)} para aplicar.</div>`
        : "";
    const linhas = d.anos.map((a) => {
      const selos = [a.ativo ? "em uso" : "", a.proximo && !a.ativo ? "próximo início" : "", a.ficticio ? "fictício" : ""].filter(Boolean)
        .map((s) => `<span style="font-size:.66rem; padding:1px 6px; border-radius:8px; border:1px solid var(--border); margin-left:6px;">${s}</span>`).join("");
      const usar = a.ativo ? "" : `<button class="btn-sm" data-acao="usar" data-ano="${a.ano}" style="padding:5px 10px;font-size:.72rem" ${d.fixado_por_ambiente ? "disabled" : ""}>Usar este ano</button>`;
      const bk = a.arquivos ? `<button class="btn-sm" data-acao="backup" data-ano="${a.ano}" style="padding:5px 10px;font-size:.72rem">Fazer backup</button>` : "";
      return `<tr><td style="padding:6px 8px;"><b>${a.ano}</b>${selos}</td>
        <td style="padding:6px 8px; color:var(--txt3);">${a.arquivos} arquivo(s)</td>
        <td style="padding:6px 8px; color:var(--txt3);">${a.backups} backup(s)</td>
        <td style="padding:6px 8px; text-align:right; white-space:nowrap;">${usar} ${bk}</td></tr>`;
    }).join("");
    const automatico = d.automatico || d.fixado_por_ambiente ? ""
      : `<div style="margin-top:8px;"><button class="btn-sm" data-acao="automatico" style="padding:6px 12px;font-size:.74rem">Voltar ao automático (ano do calendário: ${escaparHtml(d.ano_do_calendario)})</button></div>`;
    caixaAnos.innerHTML = `<table style="width:100%; border-collapse:collapse; font-size:.8rem;">${linhas}</table>${automatico}`;

    const consulta = !!d.somente_consulta;
    [["cfg-ano-restaurar", "restaurar dados"], ["cfg-ano-gerar", "criar dados fictícios"]].forEach(([id, o]) => {
      const b = el(id);
      if (b) { b.disabled = consulta; b.title = consulta ? `Somente consulta: volte ao ano atual para ${o}.` : ""; }
    });
    if (consulta) {
      aviso.innerHTML += `<div style="color:var(--amber); font-size:.8rem; margin-bottom:10px;">🔒 Somente consulta: aqui você pode trocar de ano, fazer backup e conferir um backup. Restaurar dados e criar dados fictícios ficam bloqueados até voltar ao ano atual.</div>`;
    }

    selBackup.innerHTML = d.backups.length
      ? d.backups.map((b) => `<option value="${escaparHtml(b.nome)}" data-ano="${escaparHtml(b.ano || "")}">${escaparHtml(b.ano ? "Ano " + b.ano : "Ano ?")} — ${escaparHtml(b.data)} — ${escaparHtml(b.tamanho)}${b.motivo ? " — " + escaparHtml(b.motivo) : ""}</option>`).join("")
      : `<option value="">Nenhum backup ainda</option>`;
  };

  /* Trocar de ano: tela de carregamento, o servidor recarrega os dados e a página é recarregada (ver trocarAnoLetivo). */
  const trocarAno = async (corpo) => {
    const alvo = corpo.automatico ? (estado && estado.ano_do_calendario) : corpo.ano;
    const r = await trocarAnoLetivo(corpo, alvo);
    if (r) { desenhar(r); mostrar(r.mensagem); }       // ano já em uso: só atualiza o painel
  };

  /* Telas de aviso depois de restaurar os dados de um ano. */
  const avisarMudancaDeAno = async (caminho, r) => {
    if (caminho === "/restaurar" && r.resultado && r.resultado.aplicado) {
      const ano = r.resultado.ano;
      if (ano === r.ativo) {
        await mostrarTelaAno({ titulo: `Dados de ${ano} restaurados`, texto: "Carregando as telas com os dados restaurados…", carregando: true, fecharEm: 1800 });
        location.reload();
      } else {
        mostrarTelaAno({
          titulo: `Dados de ${ano} restaurados`,
          texto: `O ano ${ano} não está em uso agora. Para visualizá-lo, escolha “Usar este ano” em ${ano}: a troca é imediata e abre em modo somente consulta.`,
          carregando: false,
        });
      }
    }
  };

  const chamar = async (botao, caminho, corpo) => {
    const original = botao ? botao.textContent : "";
    if (botao) { botao.disabled = true; botao.textContent = "Aguarde..."; }
    try {
      const r = await apiPost(`${BASE}${caminho}`, corpo);
      desenhar(r);
      mostrar(r.mensagem);
      carregarContextoAno().catch(() => {});
      await avisarMudancaDeAno(caminho, r);
      return r;
    } catch (e) {
      mostrar(e.message);
    } finally {
      if (botao && botao.isConnected) { botao.disabled = false; botao.textContent = original; }
    }
  };

  caixaAnos.addEventListener("click", (ev) => {
    const b = ev.target.closest("button[data-acao]");
    if (!b) return;
    if (b.dataset.acao === "usar") trocarAno({ ano: b.dataset.ano });
    else if (b.dataset.acao === "automatico") trocarAno({ automatico: true });
    else if (b.dataset.acao === "backup") chamar(b, "/backup", { ano: b.dataset.ano });
  });

  const dadosRestauracao = () => {
    const opcao = selBackup.selectedOptions[0];
    if (!opcao || !opcao.value) { toast("Escolha um backup"); return null; }
    return { backup: opcao.value, ano: opcao.dataset.ano || "?", so_dados: el("cfg-ano-sodados").checked };
  };
  el("cfg-ano-conferir").addEventListener("click", (ev) => {
    const r = dadosRestauracao();
    if (r) chamar(ev.currentTarget, "/restaurar", { backup: r.backup, so_dados: r.so_dados, aplicar: false });
  });
  el("cfg-ano-restaurar").addEventListener("click", (ev) => {
    const r = dadosRestauracao();
    if (!r) return;
    const mesmo = estado && r.ano === estado.ativo ? "\n\nEste é o ano em uso: as telas vão mostrar os dados restaurados." : "";
    if (!window.confirm(`Restaurar os dados do ano ${r.ano} a partir de "${r.backup}"?\n\nOs arquivos do ano ${r.ano} serão SUBSTITUÍDOS pelos do backup. Antes disso é feita uma cópia de segurança do estado atual.${mesmo}`)) return;
    chamar(ev.currentTarget, "/restaurar", { backup: r.backup, so_dados: r.so_dados, aplicar: true, confirmar: true });
  });
  el("cfg-ano-gerar").addEventListener("click", (ev) => {
    const ano = inFict.value.trim();
    if (!/^\d{4}$/.test(ano)) { toast("Informe o ano com 4 números (ex.: 2025)"); return; }
    chamar(ev.currentTarget, "/dados-ficticios", { ano, backup: true });
  });

  try {
    desenhar(await apiGet(BASE));
    msg.textContent = "";
  } catch (e) {
    status.textContent = "Não foi possível carregar o ano letivo.";
  }
}

async function conectarFormModelosParecer() {
  const inArquivo = document.getElementById("cfg-mp-arquivo");
  const caixaTurmas = document.getElementById("cfg-mp-turmas");
  const status = document.getElementById("cfg-mp-status");
  const btn = document.getElementById("cfg-mp-enviar");
  if (!inArquivo || !caixaTurmas || !status || !btn) return;

  const desenhar = (d) => {
    const turmas = d.turmas || [];
    if (!turmas.length) {
      caixaTurmas.innerHTML = "Ainda não há turmas: execute primeiro a automação Turmas.";
      return;
    }
    caixaTurmas.innerHTML = turmas.map((t, i) => {
      const modelo = t.arquivo
        ? `<span style="color:${t.arquivo_existe ? "var(--txt3)" : "var(--amber)"};"> — ${escaparHtml(t.arquivo)}${t.arquivo_existe ? "" : " (arquivo não encontrado)"}</span>`
        : `<span style="color:var(--txt3);"> — sem modelo</span>`;
      return `<label style="display:flex; gap:8px; align-items:center; padding:3px 0; cursor:pointer;">
        <input type="checkbox" class="cfg-mp-turma" value="${escaparHtml(t.turma)}" id="cfg-mp-t${i}"> <span>${escaparHtml(t.turma)}${modelo}</span></label>`;
    }).join("");
    status.textContent = d.pasta ? `Modelos ficam em ${d.pasta}` : "";
  };

  try {
    desenhar(await apiGet("/configuracoes/modelos-parecer"));
  } catch (e) {
    caixaTurmas.textContent = "Não foi possível carregar as turmas.";
  }

  btn.addEventListener("click", async () => {
    const arquivo = inArquivo.files[0];
    const marcadas = Array.from(caixaTurmas.querySelectorAll(".cfg-mp-turma:checked")).map((el) => el.value);
    if (!arquivo) { toast("Escolha o arquivo do modelo (.docx)"); return; }
    if (!marcadas.length) { toast("Marque pelo menos uma turma"); return; }
    const dados = new FormData();
    dados.append("arquivo", arquivo);
    marcadas.forEach((t) => dados.append("turmas", t));
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Enviando...";
    try {
      const res = await fetch(`${API_BASE}/configuracoes/modelos-parecer`, { method: "POST", body: dados });
      let r = null;
      try { r = await res.json(); } catch (e) { /* resposta sem JSON */ }
      if (!res.ok) throw new Error((r && (r.erro || r.mensagem)) || "Não foi possível enviar o modelo");
      inArquivo.value = "";
      desenhar(r);
      toast(r.mensagem || "Modelo salvo");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
}

async function conectarFormSenhaPrematricula() {
  const inLogin = document.getElementById("cfg-prem-login");
  const inSenha = document.getElementById("cfg-prem-senha");
  const status = document.getElementById("cfg-prem-status");
  const btn = document.getElementById("cfg-prem-salvar");
  if (!inLogin || !inSenha || !status || !btn) return;

  let senhaSalva = false;
  const mostrar = (d) => {
    senhaSalva = !!d.senha_salva;
    if (d.login) inLogin.value = d.login;
    inSenha.placeholder = senhaSalva ? "•••••••• (salva — deixe vazio para manter)" : "••••••••";
    status.textContent = d.configurada
      ? "✓ Credenciais configuradas."
      : "Credenciais ainda não configuradas.";
  };
  try {
    mostrar(await apiGet("/configuracoes/prematricula"));
  } catch (e) {
    status.textContent = "Não foi possível ler a configuração atual.";
  }

  btn.addEventListener("click", async () => {
    const login = inLogin.value.trim();
    const senha = inSenha.value;
    if (!login) { toast("Informe o login da pré-matrícula"); return; }
    if (!senha && !senhaSalva) { toast("Informe a senha da pré-matrícula"); return; }
    const original = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Salvando...";
    try {
      const r = await apiPost("/configuracoes/prematricula", { login, senha });
      inSenha.value = "";   // não deixa a senha digitada na tela
      mostrar(r);
      toast(r.mensagem || "Credenciais salvas");
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
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

/* ---------- Mandar mensagem (fila da pré-matrícula) ---------- */

async function abrirMensagemPrematricula(id) {
  let modelo;
  try {
    const res = await fetch(`${API_BASE}/whatsapp/modelo-prematricula?id=${encodeURIComponent(id)}`);
    try { modelo = await res.json(); } catch (e) { modelo = {}; }
    if (res.status === 404 && !modelo.erro) {
      throw new Error("O servidor não tem a rota de mensagens. Reinicie o AUTO SERE (o whatsapp.py novo não foi carregado).");
    }
    if (!res.ok) throw new Error(modelo.erro || "Não consegui preparar a mensagem.");
  } catch (e) {
    toast(e.message);
    return;
  }
  if (!modelo.telefone) {
    toast("Este responsável não tem telefone coletado ainda.");
    return;
  }
  let status = {};
  try { status = await apiGet("/whatsapp/status"); } catch (e) { /* segue: o envio mostra o erro */ }
  const real = !status.simulado;

  abrirModal(`Mensagem para o responsável de ${modelo.nome}`, (corpo, fechar) => {
    corpo.innerHTML = `
      <div class="field"><label>WhatsApp do responsável</label>
        <input type="text" id="mdl-msg-numero" value="${escaparHtml(modelo.telefone)}" autocomplete="off"></div>
      <div class="field"><label>Mensagem</label>
        <textarea id="mdl-msg-texto" rows="16" maxlength="4000"
          style="width:100%;background:var(--input-bg);color:var(--txt);border:1px solid var(--border);border-radius:8px;padding:10px;font:inherit;resize:vertical">${escaparHtml(modelo.texto)}</textarea></div>
      ${real ? `<label class="checklist-item" style="margin-bottom:10px"><input type="checkbox" id="mdl-msg-confirmo"> Confirmo o envio de uma mensagem de verdade</label>`
             : `<p style="color:var(--txt3);font-size:.78rem;margin-bottom:10px">Modo simulado: nada será enviado de verdade.</p>`}
      <div id="mdl-msg-erro" style="color:var(--rose);font-size:.78rem;min-height:1.1em;margin-bottom:8px"></div>
      <div class="modal-acoes">
        <button class="btn-sm" id="mdl-msg-cancelar" style="padding:9px 16px;font-size:.78rem">Cancelar</button>
        <button class="btn-primary" id="mdl-msg-enviar">Enviar</button>
      </div>`;
    const erro = corpo.querySelector("#mdl-msg-erro");
    const btn = corpo.querySelector("#mdl-msg-enviar");
    corpo.querySelector("#mdl-msg-cancelar").addEventListener("click", fechar);
    btn.addEventListener("click", async () => {
      const confirmo = !!corpo.querySelector("#mdl-msg-confirmo")?.checked;
      if (real && !confirmo) { erro.textContent = "Marque a confirmação para enviar de verdade."; return; }
      btn.disabled = true;
      erro.textContent = "";
      try {
        const r = await apiPost("/whatsapp/enviar", {
          numero: corpo.querySelector("#mdl-msg-numero").value,
          texto: corpo.querySelector("#mdl-msg-texto").value,
          confirmo,
        });
        fechar();
        toast(r.mensagem || "Mensagem enviada.");
      } catch (e) {
        erro.textContent = e.message;
        btn.disabled = false;
      }
    });
  });
}

document.addEventListener("click", (ev) => {
  const link = ev.target.closest("[data-mensagem]");
  if (!link) return;
  ev.preventDefault();
  abrirMensagemPrematricula(link.dataset.mensagem);
});

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

/* ---------- Wizard: painel "Registro de atividades" ---------- */

let _monitorWizard = null;
let _wizardAssinatura = null;      // null = nada desenhado ainda (força o 1º desenho, inclusive o estado vazio)
let _wizardEmExecucao = null;      // null = ainda não houve leitura (não recarrega a lista na 1ª)
let _wizardEntradas = [];

function iniciarMonitorWizard() {
  pararMonitorWizard();
  _wizardEmExecucao = null;
  _wizardAssinatura = null;
  atualizarAtividadeWizard();
  _monitorWizard = setInterval(atualizarAtividadeWizard, 1500);
}

function pararMonitorWizard() {
  if (_monitorWizard) {
    clearInterval(_monitorWizard);
    _monitorWizard = null;
  }
}

function _rotuloPasso(chave) {
  const p = PASSOS_WIZARD.find((x) => x.chave === chave);
  if (!p) return chave;
  const curto = p.nome.replace(/^Executar\s+/i, "").replace(/\s*\(.*$/, "").replace(/^Salvar\s+/i, "");
  return curto.charAt(0).toUpperCase() + curto.slice(1);
}

async function atualizarAtividadeWizard() {
  const corpo = document.getElementById("wizard-log-corpo");
  if (!corpo) return;
  let dados;
  try {
    dados = await apiGet("/wizard/atividade");
  } catch (e) {
    return;   // servidor ocupado ou fora do ar: tenta de novo no próximo ciclo
  }
  _wizardEntradas = dados.entradas || [];

  const status = document.getElementById("wizard-log-status");
  if (status) {
    status.innerHTML = "";
    if ((dados.executando || []).length) {
      const on = document.createElement("span");
      on.className = "on";
      on.textContent = "● Executando: " + dados.executando.map(_rotuloPasso).join(", ");
      status.appendChild(on);
    } else {
      status.textContent = _wizardEntradas.length ? "Nada em execução" : "Aguardando…";
    }
  }

  const assinatura = _wizardEntradas.map((e) => e.t + "|" + e.texto).join("\n");
  if (assinatura !== _wizardAssinatura) {
    _wizardAssinatura = assinatura;
    const noFim = corpo.scrollTop + corpo.clientHeight >= corpo.scrollHeight - 24;
    if (!_wizardEntradas.length) {
      const vazio = document.createElement("div");
      vazio.className = "wl-vazio";
      vazio.textContent = "Nada aconteceu ainda. Quando você executar um passo, o que o sistema está fazendo aparece aqui, em tempo real.";
      corpo.replaceChildren(vazio);
    } else {
      corpo.replaceChildren(..._wizardEntradas.map((e) => {
        const linha = document.createElement("div");
        linha.className = "wl wl-" + e.nivel;
        const h = document.createElement("span");
        h.className = "h";
        h.textContent = e.hora;
        const p = document.createElement("span");
        p.className = "p";
        p.textContent = _rotuloPasso(e.passo);
        const t = document.createElement("span");
        t.className = "t";
        t.textContent = e.texto;
        linha.append(h, p, t);
        return linha;
      }));
    }
    if (noFim) corpo.scrollTop = corpo.scrollHeight;
  }

  // Quando um passo começa ou termina, atualiza a lista (Concluído / Executando…).
  const agora = (dados.executando || []).join(",");
  if (_wizardEmExecucao !== null && agora !== _wizardEmExecucao) carregarWizard();
  _wizardEmExecucao = agora;
}

function conectarPainelWizard() {
  const copiar = document.getElementById("wizard-log-copiar");
  const limpar = document.getElementById("wizard-log-limpar");
  if (!copiar || !limpar) return;

  copiar.addEventListener("click", async () => {
    if (!_wizardEntradas.length) { toast("Não há registros para copiar"); return; }
    const texto = _wizardEntradas.map((e) => `${e.hora} [${_rotuloPasso(e.passo)}] ${e.texto}`).join("\n");
    try {
      await navigator.clipboard.writeText(texto);
      toast("Registro copiado");
    } catch (e) {
      const area = document.createElement("textarea");
      area.value = texto;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
      toast("Registro copiado");
    }
  });

  limpar.addEventListener("click", async () => {
    try {
      await apiPost("/wizard/atividade/limpar", {});
    } catch (e) {
      toast(e.message);
    }
    _wizardAssinatura = null;
    atualizarAtividadeWizard();
  });
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
  let passosAtivos = {};
  try {
    status = await apiGet("/wizard/status");
  } catch (e) {
    console.warn("Wizard: endpoint /wizard/status ainda não conectado", e);
  }
  try {
    passosAtivos = (await apiGet("/wizard/atividade")).passos || {};
  } catch (e) {
    // sem o painel de atividades: segue sem mostrar passos em execução
  }

  container.innerHTML = PASSOS_WIZARD.map((p, i) => {
    const concluido = status[p.chave] === true;
    const executando = (passosAtivos[p.chave] || {}).status === "executando";
    let acao;
    if (executando) {
      acao = `<span class="badge bg-cyan">Executando…</span>
              <button class="btn-sm" data-wizard-cancel="${p.chave}" style="margin-left:8px">Cancelar</button>`;
    } else if (concluido) {
      acao = '<span class="badge bg-lime">Concluído</span>';
    } else {
      acao = `<button class="btn-sm" data-wizard-run="${p.chave}">Executar</button>`;
    }
    return `
      <div class="wizard-step ${concluido && !executando ? "done" : ""}">
        <div class="wizard-num">${concluido && !executando ? icon("check") : i + 1}</div>
        <div class="txt">
          <div class="name">${p.nome}</div>
          <div class="desc">${p.desc}</div>
        </div>
        <div class="status">${acao}</div>
      </div>`;
  }).join("");

  container.querySelectorAll("[data-wizard-cancel]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await apiPost(`/automacoes/wizard_${btn.dataset.wizardCancel}/cancelar`, {});
        toast(r.mensagem || "Cancelamento solicitado");
      } catch (e) {
        toast(e.message);
        btn.disabled = false;
      }
      atualizarAtividadeWizard();
    });
  });

  container.querySelectorAll("[data-wizard-run]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const chave = btn.dataset.wizardRun;
      let payload = {};

      if (chave === "escola") {
        abrirModalEscola(() => carregarWizard());
        return;
      }

      if (chave === "whatsapp") {
        // A conexão (QR Code) é feita na própria tela do WhatsApp.
        document.querySelector('.nav-item[data-view="whatsapp"]')?.click();
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
        atualizarAtividadeWizard();   // mostra já o início do passo, sem esperar o próximo ciclo
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
  conectarPainelWizard();
  carregarPainel();
  iniciarContextoAno();
  abrirAssistenteSeNecessario();
});