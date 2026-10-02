/* ============================================================
   AUTO SERE — calendario.js
   Tela "Calendário letivo". Tudo fica dentro de uma IIFE para não
   colidir com os globais do app.js; só `carregarCalendario` é exposta
   (chamada por irPara("calendario") no app.js).
   API: /web/api/calendario/...
   ============================================================ */
(function () {
  "use strict";

  const API = "/web/api/calendario";
  const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
  const DIAS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
  const TIPOS = { municipal: "Feriado municipal", recesso: "Recesso", emenda: "Emenda de feriado", htpc: "HTPC", outro: "Outro" };
  // classe de cor por tipo de evento (padrão: feriado=vermelho, recesso/emenda=azul claro, htpc=verde-limão)
  const COR_EVENTO = { municipal: "feriado", recesso: "recesso", emenda: "recesso", htpc: "htpc", outro: "outro" };

  const agora = new Date();
  const st = {
    ano: agora.getFullYear(),
    mes: agora.getMonth(),
    vista: "mes",
    feriados: {},
    fixos: {}, // feriados fixos de Ponta Grossa + datas comemorativas, por ano
    eventos: [],
    periodos: [],
    sel: null, // seleção de intervalo para "Marcar no calendário"
    dia: null, // dia aberto no detalhe
    falhas: new Set(),
  };

  const $ = (id) => document.getElementById(id);
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`;
  const parse = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, d));
  };
  const dow = (s) => parse(s).getUTCDay();
  const br = (s) => s.split("-").reverse().join("/");
  const esc = (t) =>
    String(t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fimEv = (e) => e.fim || e.inicio;
  const HOJE = iso(agora.getFullYear(), agora.getMonth(), agora.getDate());

  /* ---------- API ---------- */
  async function api(path, opt) {
    const r = await fetch(`${API}${path}`, opt);
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.erro || `Erro ${r.status}`);
    return j;
  }
  function enviarJson(path, corpo) {
    return api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corpo),
    });
  }
  const aviso = (msg) => toast(msg); // toast() vem do app.js

  /* ---------- dados ---------- */
  async function garantirFeriados(ano) {
    if (!st.fixos[ano]) {
      try {
        st.fixos[ano] = await api(`/fixos/${ano}`);
      } catch (e) {
        /* sem as datas fixas a tela ainda funciona */
      }
    }
    if (st.feriados[ano]) return;
    try {
      st.feriados[ano] = await api(`/feriados/${ano}`);
      st.falhas.delete(ano);
    } catch (e) {
      st.falhas.add(ano);
    }
  }
  async function anosNecessarios() {
    const anos = new Set([st.ano]);
    [...st.eventos, ...st.periodos].forEach((x) => {
      anos.add(+x.inicio.slice(0, 4));
      anos.add(+fimEv(x).slice(0, 4));
    });
    await Promise.all([...anos].map(garantirFeriados));
  }
  async function carregar() {
    const d = await api("/dados");
    st.eventos = d.eventos;
    st.periodos = d.periodos;
    await anosNecessarios();
    render();
  }

  /* ---------- regras do dia ---------- */
  function info(s) {
    const ano = s.slice(0, 4);
    const nac = (st.feriados[ano] || []).filter((f) => f.date === s);
    const fix = (st.fixos[ano] || []).filter((f) => f.date === s);
    const fer = fix.filter((f) => f.tipo === "municipal"); // feriados de Ponta Grossa
    const com = fix.filter((f) => f.tipo === "comemorativa"); // estrela roxa
    const ev = st.eventos.filter((e) => s >= e.inicio && s <= fimEv(e));
    const per = st.periodos.filter((p) => s >= p.inicio && s <= p.fim);
    const ferias = per.some((p) => p.tipo === "ferias");
    const letivoPer = per.some((p) => p.tipo !== "ferias");
    const wd = dow(s);
    const util = wd > 0 && wd < 6;
    const feriado = nac.length > 0 || fer.length > 0 || ev.some((e) => e.tipo === "municipal");
    const recesso = ev.some((e) => e.tipo === "recesso" || e.tipo === "emenda");
    const htpc = ev.some((e) => e.tipo === "htpc");
    const outro = ev.some((e) => e.tipo === "outro");
    // prioridade da cor: feriado > recesso/emenda > HTPC > outro > férias
    const cat = feriado ? "feriado" : recesso ? "recesso" : htpc ? "htpc" : outro ? "outro" : ferias ? "ferias" : "";
    // comemorativas NÃO tiram o dia letivo
    const letivo = letivoPer && !ferias && util && !nac.length && !fer.length && !ev.length;
    return { nac, fer, com, ev, per, ferias, letivoPer, util, cat, letivo };
  }
  function contarLetivos(a, b) {
    let n = 0;
    const d = parse(a);
    const fim = parse(b);
    for (; d <= fim; d.setUTCDate(d.getUTCDate() + 1)) {
      if (info(d.toISOString().slice(0, 10)).letivo) n++;
    }
    return n;
  }
  function previaSel(s) {
    const x = st.sel;
    if (!x || !x.a) return false;
    const b = x.b || x.a;
    const [i, f] = x.a <= b ? [x.a, b] : [b, x.a];
    return s >= i && s <= f;
  }

  /* ---------- renderização ---------- */
  function renderMes() {
    const first = new Date(Date.UTC(st.ano, st.mes, 1)).getUTCDay();
    const n = new Date(Date.UTC(st.ano, st.mes + 1, 0)).getUTCDate();
    let h = DIAS.map((d) => `<div class="cal-dow">${d}</div>`).join("");
    for (let i = 0; i < first; i++) h += '<div class="cal-cell vazio"></div>';
    let letivos = 0;
    let feriados = 0;
    for (let d = 1; d <= n; d++) {
      const s = iso(st.ano, st.mes, d);
      const i = info(s);
      const wd = dow(s);
      if (i.letivo) letivos++;
      if (i.nac.length || i.fer.length || i.ev.length) feriados++;
      const cls = ["cal-cell"];
      if (wd === 0 || wd === 6) cls.push("fds");
      if (i.cat) cls.push(`c-${i.cat}`);
      if (s === HOJE) cls.push("hoje");
      if (s === st.dia) cls.push("ativo");
      if (previaSel(s)) cls.push("previa");
      const chips = [
        ...i.nac.map((f) => `<span class="cal-chip feriado" title="${esc(f.name)}">${esc(f.name)}</span>`),
        ...i.fer.map((f) => `<span class="cal-chip feriado" title="${esc(f.name)}">${esc(f.name)}</span>`),
        ...i.ev.map((e) => `<span class="cal-chip ${COR_EVENTO[e.tipo] || "outro"}" title="${esc(e.nome)}">${esc(e.nome)}</span>`),
        ...i.com.map((f) => `<span class="cal-chip star" title="${esc(f.name)}">★ ${esc(f.name)}</span>`),
      ].join("");
      h += `<button class="${cls.join(" ")}" data-d="${s}" aria-label="${d} de ${MESES[st.mes]}"><span class="cal-num">${d}</span>${chips}</button>`;
    }
    $("cal-vista").innerHTML = `<div class="cal-grade">${h}</div>`;
    $("cal-rodape-mes").innerHTML = `<span>Dias letivos no mês: <b>${letivos}</b></span><span>Dias com feriado ou recesso: <b>${feriados}</b></span>`;
  }

  function renderAno() {
    let h = "";
    for (let m = 0; m < 12; m++) {
      const first = new Date(Date.UTC(st.ano, m, 1)).getUTCDay();
      const n = new Date(Date.UTC(st.ano, m + 1, 0)).getUTCDate();
      let g = DIAS.map((d) => `<span class="h">${d[0]}</span>`).join("");
      for (let i = 0; i < first; i++) g += "<span></span>";
      for (let d = 1; d <= n; d++) {
        const s = iso(st.ano, m, d);
        const i = info(s);
        const c = i.cat + (i.com.length ? " star" : "");
        const t = [...i.nac.map((f) => f.name), ...i.fer.map((f) => f.name), ...i.ev.map((e) => e.nome), ...i.com.map((f) => "★ " + f.name)].join(", ");
        g += `<i class="cal-mc ${c}" data-d="${s}" title="${esc(t)}">${d}</i>`;
      }
      h += `<div class="cal-mini-mes"><h3><button data-m="${m}">${MESES[m]}</button></h3><div class="cal-mini-g">${g}</div></div>`;
    }
    $("cal-vista").innerHTML = `<div class="cal-ano">${h}</div>`;
    let letivos = 0;
    for (let m = 0; m < 12; m++) {
      const n = new Date(Date.UTC(st.ano, m + 1, 0)).getUTCDate();
      for (let d = 1; d <= n; d++) if (info(iso(st.ano, m, d)).letivo) letivos++;
    }
    $("cal-rodape-mes").innerHTML = `<span>Dias letivos em ${st.ano}: <b>${letivos}</b></span>`;
  }

  function renderDetalhe() {
    const el = $("cal-detalhe");
    if (!st.dia) {
      el.hidden = true;
      return;
    }
    const s = st.dia;
    const i = info(s);
    const titulo = parse(s).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
    const itens = [
      ...i.nac.map((f) => `<li><span><b>${esc(f.name)}</b> · feriado nacional</span></li>`),
      ...i.fer.map((f) => `<li><span><b>${esc(f.name)}</b> · feriado municipal</span></li>`),
      ...i.com.map((f) => `<li><span class="cal-estrela">★ <b>${esc(f.name)}</b> · data comemorativa</span></li>`),
      ...i.ev.map(
        (e) => `<li><span><b>${esc(e.nome)}</b> · ${TIPOS[e.tipo]}</span><button class="btn-sm cal-btn-del" data-del="eventos:${e.id}">Excluir</button></li>`
      ),
      ...i.per.map((p) => `<li><span><b>${esc(p.nome)}</b> · ${p.tipo === "ferias" ? "férias escolares" : "período letivo"}</span></li>`),
    ];
    const status = i.letivo
      ? "Dia letivo."
      : i.ferias
        ? "Férias escolares."
        : i.letivoPer
          ? "Dentro de um período letivo, mas sem aula."
        : i.util
          ? "Fora dos períodos letivos."
          : "Fim de semana.";
    el.hidden = false;
    el.innerHTML = `<h3>${titulo}</h3>${itens.length ? `<ul>${itens.join("")}</ul>` : ""}<p class="cal-vazio-msg">${status}</p>
      <button class="btn-sm" id="cal-add-dia">Adicionar recesso ou feriado neste dia</button>`;
  }

  function renderLateral() {
    const per = [...st.periodos].sort((a, b) => a.inicio.localeCompare(b.inicio));
    $("cal-lista-periodos").innerHTML = per.length
      ? per
          .map(
            (p) => `<li><div><div class="t"><i class="cal-dot ${p.tipo === "ferias" ? "ferias" : "letivo"}"></i>${esc(p.nome)}</div>
        <div class="s">${br(p.inicio)} a ${br(p.fim)} · ${p.tipo === "ferias" ? "férias escolares" : contarLetivos(p.inicio, p.fim) + " dias letivos"}</div></div>
        <button class="btn-sm cal-btn-del" data-del="periodos:${p.id}">Excluir</button></li>`
          )
          .join("")
      : '<li><span class="s">Nenhum período cadastrado.</span></li>';

    const ev = [...st.eventos].sort((a, b) => a.inicio.localeCompare(b.inicio));
    $("cal-lista-eventos").innerHTML = ev.length
      ? ev
          .map(
            (e) => `<li><div><div class="t"><i class="cal-dot ${COR_EVENTO[e.tipo] || "outro"}"></i>${esc(e.nome)}</div>
        <div class="s">${TIPOS[e.tipo]} · ${br(e.inicio)}${fimEv(e) !== e.inicio ? " a " + br(fimEv(e)) : ""}</div></div>
        <button class="btn-sm cal-btn-del" data-del="eventos:${e.id}">Excluir</button></li>`
          )
          .join("")
      : '<li><span class="s">Nenhum recesso, emenda ou HTPC cadastrado.</span></li>';

    const nac = st.feriados[st.ano] || [];
    $("cal-nac-resumo").textContent = `Feriados nacionais de ${st.ano} (${nac.length})`;
    $("cal-lista-nac").innerHTML = nac.map((f) => `<li><span>${esc(f.name)}</span><span>${br(f.date)}</span></li>`).join("");
  }

  function renderAviso() {
    const f = [...st.falhas];
    $("cal-aviso").classList.toggle("on", f.length > 0);
    if (f.length) $("cal-aviso-txt").textContent = `Não foi possível carregar os feriados nacionais de ${f.join(", ")}. Confira a conexão com a internet.`;
  }
  function renderSelecao() {
    const x = st.sel;
    $("cal-selecao").classList.toggle("on", !!x);
    if (x) $("cal-selecao-txt").textContent = x.passo === 0 ? "Clique no primeiro dia do período." : "Agora clique no último dia.";
  }

  function render() {
    $("cal-titulo").textContent = st.vista === "mes" ? `${MESES[st.mes]} de ${st.ano}` : String(st.ano);
    $("cal-v-mes").setAttribute("aria-pressed", st.vista === "mes");
    $("cal-v-ano").setAttribute("aria-pressed", st.vista === "ano");
    st.vista === "mes" ? renderMes() : renderAno();
    renderDetalhe();
    renderLateral();
    renderAviso();
    renderSelecao();
  }

  /* ---------- interação ---------- */
  async function ir(ano, mes) {
    st.ano = ano;
    if (mes !== undefined) st.mes = mes;
    await garantirFeriados(st.ano);
    render();
  }

  function iniciarSel(alvo) {
    st.sel = { alvo, passo: 0, a: null, b: null };
    st.vista = "mes";
    render();
  }
  function cancelarSel() {
    st.sel = null;
    render();
  }

  function clicouDia(s) {
    const x = st.sel;
    if (x) {
      if (x.passo === 0) {
        x.a = s;
        x.b = null;
        x.passo = 1;
      } else {
        let [a, b] = [x.a, s];
        if (b < a) [a, b] = [b, a];
        $("cal-p-inicio").value = a;
        $("cal-p-fim").value = b;
        st.sel = null;
        $("cal-p-nome").focus();
      }
      render();
      return;
    }
    st.dia = s;
    $("cal-e-inicio").value = s;
    render();
  }

  async function enviar(path, corpo, form) {
    try {
      const r = await enviarJson(path, corpo);
      form.reset();
      aviso("Salvo.");
      st.ano = +r.inicio.slice(0, 4);
      st.mes = +r.inicio.slice(5, 7) - 1;
      st.vista = "mes";
      await carregar();
    } catch (err) {
      aviso(err.message);
    }
  }

  function init() {
    $("cal-prev").onclick = () => {
      if (st.vista === "ano") return ir(st.ano - 1);
      st.mes === 0 ? ir(st.ano - 1, 11) : ir(st.ano, st.mes - 1);
    };
    $("cal-next").onclick = () => {
      if (st.vista === "ano") return ir(st.ano + 1);
      st.mes === 11 ? ir(st.ano + 1, 0) : ir(st.ano, st.mes + 1);
    };
    $("cal-hoje").onclick = () => {
      st.vista = "mes";
      ir(agora.getFullYear(), agora.getMonth());
    };
    $("cal-v-mes").onclick = () => {
      st.vista = "mes";
      render();
    };
    $("cal-v-ano").onclick = () => {
      st.vista = "ano";
      render();
    };
    $("cal-aviso-retry").onclick = async () => {
      await anosNecessarios();
      render();
    };
    $("cal-marcar-periodo").onclick = () => iniciarSel("periodo");
    $("cal-selecao-cancel").onclick = cancelarSel;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && st.sel) cancelarSel();
    });

    $("cal-vista").addEventListener("click", (e) => {
      const m = e.target.closest("[data-m]");
      if (m) {
        st.mes = +m.dataset.m;
        st.vista = "mes";
        return render();
      }
      const c = e.target.closest("[data-d]");
      if (!c) return;
      if (st.vista === "ano" && !st.sel) {
        st.dia = c.dataset.d;
        $("cal-e-inicio").value = c.dataset.d;
        st.mes = +c.dataset.d.slice(5, 7) - 1;
        st.vista = "mes";
        return render();
      }
      clicouDia(c.dataset.d);
    });
    $("cal-detalhe").addEventListener("click", (e) => {
      if (e.target.closest("#cal-add-dia")) {
        $("cal-e-inicio").value = st.dia;
        $("cal-e-nome").focus();
      }
    });

    // Exclusão (botões estão no detalhe e nas listas laterais)
    $("sec-calendario").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-del]");
      if (!b) return;
      const [rota, id] = b.dataset.del.split(":");
      if (!confirm("Excluir este registro?")) return;
      try {
        await api(`/${rota}/${id}`, { method: "DELETE" });
        aviso("Registro excluído.");
        await carregar();
      } catch (err) {
        aviso(err.message);
      }
    });

    $("cal-f-periodo").addEventListener("submit", (e) => {
      e.preventDefault();
      enviar("/periodos", { nome: $("cal-p-nome").value, tipo: $("cal-p-tipo").value, inicio: $("cal-p-inicio").value, fim: $("cal-p-fim").value }, e.target);
    });
    $("cal-f-evento").addEventListener("submit", (e) => {
      e.preventDefault();
      enviar("/eventos", { nome: $("cal-e-nome").value, tipo: $("cal-e-tipo").value, inicio: $("cal-e-inicio").value }, e.target);
    });
  }

  /** Chamada por irPara("calendario"): recarrega dados e redesenha. */
  window.carregarCalendario = function () {
    carregar().catch((err) => {
      aviso(err.message);
      render();
    });
  };

  init();
})();
