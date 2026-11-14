/* ============================================================
   AUTO SERE — previsao.js
   Módulo "Previsão <ano letivo + 1>": todos os alunos rematriculados para o
   próximo ano + os alunos novos da pré-matrícula (GET /web/api/previsao).
   Tudo numa IIFE; só `carregarPrevisao` é exposta (chamada por irPara("previsao")).
   ============================================================ */
(function () {
  "use strict";

  const estado = { aba: "todos", busca: "", dados: null };
  let ligada = false;

  const $ = (id) => document.getElementById(id);
  const esc = (v) => escaparHtml(v);

  function filtradas() {
    if (!estado.dados) return [];
    const q = semAcento(estado.busca.trim());
    return estado.dados.linhas.filter((l) => {
      if (estado.aba !== "todos" && l.tipo !== estado.aba) return false;
      if (!q) return true;
      return [l.nome, l.cgm, l.cpf, l.turma, l.responsavel].some((c) => semAcento(c).includes(q));
    });
  }

  function rotuloSituacao(l) {
    if (l.tipo === "rematriculado") return badge("Rematriculado", "bg-lime");
    if (l.situacao === "matriculado") return badge("Vaga confirmada", "bg-cyan");
    return badge("Aguardando", "bg-amber");
  }

  function desenharCartoes(d) {
    const meta = { cyan: "cyan", lime: "lime", amber: "amber" };
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
    $("pv-tbody").innerHTML = linhas.map((l) => {
      const aviso = l.ja_e_aluno && l.tipo === "novo"
        ? ` <span class="badge bg-muted" title="Já consta como aluno da escola neste ano, sem rematrícula confirmada">já é aluno</span>` : "";
      const origem = l.tipo === "novo" && (l.escola_origem || l.turma_origem)
        ? `<small>vem de ${esc([l.turma_origem, l.escola_origem].filter(Boolean).join(" · "))}</small>` : "";
      return `<tr>
        <td class="td-name">${esc(l.nome || "—")}${aviso}${origem}</td>
        <td>${l.tipo === "novo" ? badge("Novo", "bg-amber") : badge("Rematrícula", "bg-lime")}</td>
        <td>${esc(l.turma || "—")}${l.posicao ? `<small>posição ${esc(l.posicao)}</small>` : ""}</td>
        <td class="td-mono">${esc(l.cgm || l.cpf || "—")}</td>
        <td>${esc(l.nascimento || "—")}</td>
        <td>${rotuloSituacao(l)}</td>
        <td>${esc(l.responsavel || "—")}${l.telefone ? `<small>${esc(l.telefone)}</small>` : ""}</td>
      </tr>`;
    }).join("");
  }

  function exportarCsv() {
    const linhas = filtradas();
    if (!linhas.length) { toast("Nada para exportar."); return; }
    const celula = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const cab = ["Nome", "Tipo", "Turma", "CGM", "CPF", "Nascimento", "Situação", "Responsável", "Telefone"];
    const rotulo = (l) => (l.tipo === "rematriculado" ? "Rematriculado" : l.situacao === "matriculado" ? "Novo - vaga confirmada" : "Novo - aguardando");
    const corpo = linhas.map((l) => [l.nome, l.tipo === "novo" ? "Novo" : "Rematriculado", l.turma, l.cgm, l.cpf, l.nascimento, rotulo(l), l.responsavel, l.telefone].map(celula).join(";"));
    const csv = "\uFEFF" + [cab.map(celula).join(";"), ...corpo].join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `previsao-${estado.dados.ano}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function ligar() {
    if (ligada) return;
    ligada = true;
    document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((b) => b.addEventListener("click", () => {
      estado.aba = b.dataset.pvtab;
      document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((x) => x.classList.toggle("active", x === b));
      desenharLinhas();
    }));
    $("pv-busca").addEventListener("input", (e) => { estado.busca = e.target.value; desenharLinhas(); });
    $("pv-exportar").addEventListener("click", exportarCsv);
  }

  async function carregarPrevisao() {
    ligar();
    try {
      estado.dados = await apiGet("/previsao");
    } catch (e) {
      estado.dados = { linhas: [], cartoes: [], avisos: [], ano: "" };
      $("pv-cartoes").innerHTML = "";
      $("pv-avisos").innerHTML = "";
      $("pv-cnt").textContent = "0";
      $("pv-tbody").innerHTML = "";
      $("pv-vazio-msg").textContent = "Não foi possível carregar /previsao.";
      $("pv-vazio").style.display = "";
      console.warn("Previsão: erro ao carregar", e);
      return;
    }
    const d = estado.dados;
    $("pv-ano").textContent = d.ano;
    const titulo = $("topbar-title");
    if (titulo && $("sec-previsao").classList.contains("active")) titulo.textContent = `Previsão ${d.ano}`;
    const c = d.contagem || {};
    const rotulos = { todos: `Todos (${c.total || 0})`, rematriculado: `Rematriculados (${c.rematriculados || 0})`, novo: `Novos (${c.novos || 0})` };
    document.querySelectorAll("#sec-previsao [data-pvtab]").forEach((b) => { b.textContent = rotulos[b.dataset.pvtab]; });
    desenharCartoes(d);
    desenharAvisos(d);
    desenharLinhas();
  }

  window.carregarPrevisao = carregarPrevisao;
})();
