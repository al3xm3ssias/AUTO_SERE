/* Direcionados GEO dentro da tela "Pré matrícula": um botão ao lado das abas de ano abre a lista completa
   (todos os dados de sere_sisgea_<ano>.json), com o telefone do responsável em destaque.
   Dados: GET /web/api/direcionados-geo. Só consulta; a coleta é a automação "fluxo_geo". */
(function () {
  "use strict";

  const est = { aberto: false, dados: null, aba: "todos", etapa: "", busca: "" };
  const $ = (id) => document.getElementById(id);
  const esc = (v) => escaparHtml(v);
  const digitos = (t) => String(t || "").replace(/\D/g, "");

  function telefoneHtml(t) {
    if (!t) return '<span style="color:var(--txt3)">—</span>';
    const d = digitos(t);
    const zap = d.length >= 10 ? `https://wa.me/${d.startsWith("55") ? d : "55" + d}` : "";
    return `<b class="td-mono" style="font-size:.9rem">${esc(t)}</b>${zap ? ` <a href="${zap}" target="_blank" rel="noopener" title="Abrir no WhatsApp" style="color:var(--cyan)">WhatsApp</a>` : ""}`;
  }

  function filtrados() {
    const q = semAcento((est.busca || "").trim());
    const qd = digitos(est.busca);
    return ((est.dados && est.dados.alunos) || []).filter((a) => {
      const ausente = a.situacao_lista === "ausente";
      if (est.aba === "ausentes" ? !ausente : ausente) return false;
      if (est.aba === "com_telefone" && !a.telefone) return false;
      if (est.aba === "sem_telefone" && a.telefone) return false;
      if (est.etapa && a.etapa !== est.etapa) return false;
      if (!q) return true;
      const texto = semAcento([a.nome, a.responsavel, a.cgm, a.etapa, a.turma, a.escola_origem, a.municipio_origem, a.telefone].join(" "));
      return texto.includes(q) || (qd.length >= 4 && digitos(a.telefone).includes(qd));
    });
  }

  function desenhar() {
    const g = est.dados || { alunos: [], existe: false, contagem: {} };
    const c = g.contagem || {};
    $("pg-ano").textContent = g.ano || "";
    $("pg-info").textContent = g.existe
      ? `${g.arquivo} · coletado em ${String(g.coletado_em || "—").replace("T", " ")}${g.coleta_completa === false ? " · coleta incompleta" : ""}`
      : "";
    const cartao = (rot, val, sub, cor, ic) => `<div class="stat-card"><div class="stat-card-icon">${icon(ic)}</div><div class="stat-lbl">${esc(rot)}</div>
      <div class="stat-val v-${cor}">${esc(val)}</div><div class="stat-sub">${esc(sub)}</div></div>`;
    $("pg-cartoes").innerHTML = g.existe ? [
      cartao("Direcionados", c.presentes || 0, "na lista do SERE", "cyan", "mapPin"),
      cartao("Com telefone", c.com_telefone || 0, "responsável com contato", "lime", "users"),
      cartao("Sem telefone", c.sem_telefone || 0, "buscar o contato", "amber", "clock"),
      cartao("Ausentes da lista", c.ausentes || 0, "possível desistência", "rose", "transfer"),
    ].join("") : "";
    const rot = { todos: `Todos (${c.presentes || 0})`, com_telefone: `Com telefone (${c.com_telefone || 0})`,
      sem_telefone: `Sem telefone (${c.sem_telefone || 0})`, ausentes: `Ausentes da lista (${c.ausentes || 0})` };
    document.querySelectorAll("#pm-geo [data-pgtab]").forEach((b) => { b.textContent = rot[b.dataset.pgtab]; b.classList.toggle("active", b.dataset.pgtab === est.aba); });
    const etapas = [...new Set((g.alunos || []).map((a) => a.etapa).filter(Boolean))];
    $("pg-etapa").innerHTML = `<option value="">Todas as etapas</option>` + etapas.map((e) => `<option value="${esc(e)}"${e === est.etapa ? " selected" : ""}>${esc(e)}</option>`).join("");
    const linhas = filtrados();
    $("pg-cnt").textContent = linhas.length;
    $("pg-tbody").innerHTML = linhas.map((a) => `<tr>
      <td>${telefoneHtml(a.telefone)}</td>
      <td>${esc(a.responsavel || "—")}</td>
      <td class="td-name">${esc(a.nome)}</td>
      <td class="td-mono">${esc(a.cgm || "—")}</td>
      <td>${esc(a.etapa || "—")}${a.turma ? `<small>${esc(a.turma)}</small>` : ""}</td>
      <td>${esc(a.escola_origem || "—")}${a.municipio_origem ? `<small>${esc(a.municipio_origem)}</small>` : ""}</td>
      <td>${a.matricula_confirmada ? '<span class="badge bg-lime">Confirmada</span>' : '<span class="badge bg-muted">Não confirmada</span>'}${a.matricula ? `<small>${esc(a.matricula)}</small>` : ""}${a.escola_destino ? `<small>${esc(a.escola_destino)}</small>` : ""}</td>
      <td>${a.documentos_pendentes.length ? a.documentos_pendentes.map((d) => `<span class="badge bg-amber">${esc(d)}</span>`).join(" ") : '<span style="color:var(--txt3)">—</span>'}</td>
      <td>${a.situacao_lista === "ausente" ? `<span class="badge bg-rose">Ausente</span><small>desde ${esc(String(a.ausente_desde).slice(0, 10).split("-").reverse().join("/"))}</small>` : '<span class="badge bg-cyan">Presente</span>'}<small>1ª vez: ${esc(String(a.primeira_vez_visto).slice(0, 10).split("-").reverse().join("/") || "—")}</small></td></tr>`).join("");
    $("pg-vazio").style.display = linhas.length ? "none" : "";
    $("pg-vazio-msg").textContent = g.existe ? "Nenhum resultado."
      : `Ainda não existe ${g.arquivo || "sere_sisgea"}. Rode a automação "Direcionados GEO" para coletar.`;
  }

  function exportar() {
    const linhas = filtrados();
    if (!linhas.length) { toast("Nada para exportar."); return; }
    const cab = ["Telefone do responsável", "Responsável", "Aluno", "CGM", "Etapa", "Turma", "Escola de origem", "Município de origem",
      "Escola de destino", "Matrícula confirmada", "Documentos pendentes", "Na lista"];
    const cel = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const corpo = linhas.map((a) => [a.telefone, a.responsavel, a.nome, a.cgm, a.etapa, a.turma, a.escola_origem, a.municipio_origem,
      a.escola_destino, a.matricula_confirmada ? "Sim" : "Não", a.documentos_pendentes.join(" | "), a.situacao_lista]);
    const csv = "\uFEFF" + [cab, ...corpo].map((l) => l.map(cel).join(";")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `direcionados-geo-${(est.dados && est.dados.ano) || ""}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  /* Mostra só a lista GEO (esconde o resto da Pré matrícula) ou devolve a tela como estava. */
  function alternar(abrir) {
    est.aberto = abrir;
    const sec = $("sec-prematricula");
    [...sec.children].forEach((el) => {
      if (el.classList.contains("page-header") || el.id === "pm-anos" || el.id === "pm-geo") return;
      if (abrir) { if (el.dataset.geoAntes === undefined) el.dataset.geoAntes = el.style.display; el.style.display = "none"; }
      else if (el.dataset.geoAntes !== undefined) { el.style.display = el.dataset.geoAntes; delete el.dataset.geoAntes; }
    });
    $("pm-geo").style.display = abrir ? "" : "none";
    const aviso = $("pm-ano-aviso");
    if (abrir) aviso.hidden = true;
    $("pm-anos").querySelectorAll("[data-pmano]").forEach((b) => b.classList.toggle("active", !abrir && b.getAttribute("aria-selected") === "true"));
    const b = $("pm-anos").querySelector("[data-pmgeo]");
    if (b) b.classList.toggle("active", abrir);
  }

  async function abrir() {
    alternar(true);
    try { est.dados = await apiGet("/direcionados-geo"); } catch (e) {
      est.dados = { alunos: [], existe: false, contagem: {} };
      toast("Não foi possível carregar os direcionados GEO");
      console.warn("Direcionados GEO:", e);
    }
    desenhar();
  }

  function garantirBotao() {
    const caixa = $("pm-anos");
    if (!caixa || caixa.querySelector("[data-pmgeo]")) return;
    const b = document.createElement("button");
    b.className = "pill" + (est.aberto ? " active" : "");
    b.type = "button"; b.dataset.pmgeo = "1";
    b.innerHTML = `Direcionados GEO <small style="opacity:.7">telefone do responsável</small>`;
    caixa.appendChild(b);
  }

  function iniciar() {
    const caixa = $("pm-anos");
    if (!caixa) return;
    garantirBotao();
    new MutationObserver(garantirBotao).observe(caixa, { childList: true });   // app.js refaz as abas de ano a cada carga
    caixa.addEventListener("click", (e) => {
      if (e.target.closest("[data-pmgeo]")) abrir();
      else if (e.target.closest("[data-pmano]") && est.aberto) alternar(false);
    });
    document.querySelectorAll("#pm-geo [data-pgtab]").forEach((b) => b.addEventListener("click", () => { est.aba = b.dataset.pgtab; desenhar(); }));
    $("pg-etapa").addEventListener("change", (e) => { est.etapa = e.target.value; desenhar(); });
    $("pg-busca").addEventListener("input", (e) => { est.busca = e.target.value; desenhar(); });
    $("pg-exportar").addEventListener("click", exportar);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();

  /* ───── Mensagem em massa: põe na fila do WhatsApp (uma por telefone). Não envia nada: a fila é que envia. ───── */
  const massa = { modelos: [], carregando: false };
  const BASE_WA = "/web/api/whatsapp";

  async function chamarWa(caminho, metodo, corpo) {
    const opts = { method: metodo || "GET", headers: { "Content-Type": "application/json" } };
    if (corpo) opts.body = JSON.stringify(corpo);
    const res = await fetch(BASE_WA + caminho, opts);
    let dados = {};
    try { dados = await res.json(); } catch (e) { /* sem corpo */ }
    return { ok: res.ok, dados };
  }

  function parametrosMassa() {
    const q = new URLSearchParams();
    if ($("pg-massa-etapa").value) q.set("etapa", $("pg-massa-etapa").value);
    if ($("pg-massa-confirmados").checked) q.set("incluir_confirmados", "1");
    return q.toString();
  }

  async function atualizarResumoMassa() {
    const r = await chamarWa("/fila/geo/resumo" + (parametrosMassa() ? "?" + parametrosMassa() : ""));
    const caixa = $("pg-massa-cartoes");
    if (!r.ok) { caixa.innerHTML = ""; $("pg-massa-amostra").textContent = r.dados.erro || "Não foi possível ler os direcionados GEO."; $("pg-massa-enfileirar").disabled = true; return; }
    const c = r.dados.contagem;
    const cartao = (rot, val, sub, cor) => `<div class="stat-card"><div class="stat-lbl">${esc(rot)}</div><div class="stat-val v-${cor}">${esc(val)}</div><div class="stat-sub">${esc(sub)}</div></div>`;
    caixa.innerHTML = [
      cartao("Mensagens", c.mensagens, `${c.alunos} aluno(s)`, "lime"),
      cartao("Já confirmados", c.ja_confirmados, "não recebem", "cyan"),
      cartao("Sem telefone", c.sem_telefone + c.telefone_invalido, "não dá para enviar", "amber"),
      cartao("Ausentes da lista", c.ausentes, "não recebem", "rose"),
    ].join("");
    const sel = $("pg-massa-etapa");
    if (sel.options.length <= 1) sel.innerHTML = `<option value="">Todas as etapas</option>` + (r.dados.etapas || []).map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
    $("pg-massa-amostra").textContent = (r.dados.amostra || []).length
      ? "Primeiros da fila: " + r.dados.amostra.map((a) => `${a.nomes} (${a.numero})`).join(" · ") : "Nenhum direcionado pode receber a mensagem.";
    $("pg-massa-enfileirar").disabled = !c.mensagens;
    $("pg-massa-enfileirar").dataset.n = c.mensagens;
    if (r.dados.coleta_completa === false) $("pg-massa-amostra").textContent += " · ATENÇÃO: a última coleta foi incompleta, rode \"Direcionados GEO\" de novo antes de enviar.";
  }

  async function abrirMassa() {
    $("pg-massa").style.display = "";
    $("pg-massa-ir").hidden = true;
    const m = await chamarWa("/fila/modelos");
    massa.modelos = (m.dados.modelos || []).filter((x) => x.id !== "livre" && x.id !== "comunicado");
    const sel = $("pg-massa-modelo");
    sel.innerHTML = massa.modelos.map((x) => `<option value="${esc(x.id)}"${x.id === "confirmar_interesse_geo" ? " selected" : ""}>${esc(x.nome)}</option>`).join("");
    trocarModelo();
    await atualizarResumoMassa();
  }

  function trocarModelo() {
    const m = massa.modelos.find((x) => x.id === $("pg-massa-modelo").value);
    $("pg-massa-texto").value = m ? m.texto : "";
  }

  async function enfileirarMassa() {
    const n = Number($("pg-massa-enfileirar").dataset.n || 0);
    if (!n) return;
    if (!confirm(`Pôr ${n} mensagem(ns) na fila do WhatsApp?\n\nNada é enviado agora: o envio só começa quando você iniciar a fila na tela WhatsApp, uma mensagem por vez, com pausa entre elas.`)) return;
    const botao = $("pg-massa-enfileirar");
    botao.disabled = true;
    try {
      const r = await chamarWa("/fila/geo/em-massa", "POST", {
        modelo_id: $("pg-massa-modelo").value, texto: $("pg-massa-texto").value, etapa: $("pg-massa-etapa").value,
        incluir_confirmados: $("pg-massa-confirmados").checked, confirmo: true,
      });
      if (!r.ok) { toast(r.dados.erro || "Não foi possível pôr na fila."); return; }
      const res = r.dados.resultado || {};
      const partes = [`${res.adicionados || 0} na fila`];
      if (res.duplicados) partes.push(`${res.duplicados} já estavam (mesmo texto, mesmo número)`);
      if ((res.invalidos || []).length) partes.push(`${res.invalidos.length} recusada(s)`);
      toast(partes.join(" · "));
      $("pg-massa-ir").hidden = false;
    } catch (e) {
      toast("Falha ao falar com o servidor.");
      console.warn("Mensagem em massa GEO:", e);
    } finally {
      botao.disabled = false;
      atualizarResumoMassa();
    }
  }

  function iniciarMassa() {
    const abrirBtn = $("pg-massa-abrir");
    if (!abrirBtn) return;
    abrirBtn.addEventListener("click", abrirMassa);
    $("pg-massa-fechar").addEventListener("click", () => { $("pg-massa").style.display = "none"; });
    $("pg-massa-modelo").addEventListener("change", trocarModelo);
    $("pg-massa-etapa").addEventListener("change", atualizarResumoMassa);
    $("pg-massa-confirmados").addEventListener("change", atualizarResumoMassa);
    $("pg-massa-enfileirar").addEventListener("click", enfileirarMassa);
    $("pg-massa-ir").addEventListener("click", () => document.querySelector('.nav-item[data-view="whatsapp"]')?.click());
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciarMassa); else iniciarMassa();
})();
