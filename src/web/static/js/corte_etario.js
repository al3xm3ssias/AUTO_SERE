/* ============================================================
   AUTO SERE — corte_etario.js
   Tela "Corte etário": em que turma a criança entra no ano letivo,
   conforme mês/ano de nascimento (Berçário ao 5º ano).
   Regra: a criança precisa ter a idade da turma completa até 31/03
   do ano letivo. Tudo roda no navegador (sem API).
   Para mudar regras ou turmas, edite as constantes abaixo.
   Tudo fica numa IIFE; só `carregarCorteEtario` é exposta
   (chamada por irPara("corte-etario") no app.js).
   ============================================================ */
(function () {
  "use strict";

  const CORTE_MES = 3;   // março (31/03)
  const CORTE_DIA = 31;

  // Berçário: aceita quem nasceu de abril até este mês no ano anterior ao ano letivo.
  // Quem nasceu depois disso ainda é muito pequeno ("Não").
  const BERCARIO_ULTIMO_MES = 8; // agosto

  // Idade completa em 31/03 -> turma
  const TURMAS = [
    { idade: 0,  nome: "Berçário" },
    { idade: 1,  nome: "Infantil 1" },
    { idade: 2,  nome: "Infantil 2" },
    { idade: 3,  nome: "Infantil 3" },
    { idade: 4,  nome: "Infantil 4" },
    { idade: 5,  nome: "Infantil 5" },
    { idade: 6,  nome: "1º ano" },
    { idade: 7,  nome: "2º ano" },
    { idade: 8,  nome: "3º ano" },
    { idade: 9,  nome: "4º ano" },
    { idade: 10, nome: "5º ano" },
  ];
  const IDADE_MAX = TURMAS[TURMAS.length - 1].idade;

  // A partir deste mês a tela já abre no ano letivo seguinte (período de matrículas).
  // Use 13 para abrir sempre no ano atual.
  const ABRIR_NO_PROXIMO_ANO_A_PARTIR_DO_MES = 11; // novembro

  const MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

  const $ = (id) => document.getElementById(id);
  const pad = (n) => String(n).padStart(2, "0");
  const dataCorte = `${pad(CORTE_DIA)}/${pad(CORTE_MES)}`;

  const anoAtual = () => new Date().getFullYear();
  const anoPadrao = () =>
    new Date().getMonth() + 1 >= ABRIR_NO_PROXIMO_ANO_A_PARTIR_DO_MES ? anoAtual() + 1 : anoAtual();
  let anoSelecionado = anoPadrao();

  /* ---------- Regras ---------- */

  /** Idade completa em 31/03 do ano letivo, para quem nasceu no dia d do mês m do ano y. */
  function idadeNoCorte(anoLetivo, y, m, d = 1) {
    const idade = anoLetivo - y;
    const depois = m > CORTE_MES || (m === CORTE_MES && d > CORTE_DIA);
    return depois ? idade - 1 : idade;
  }

  /** Turma de quem nasceu no mês m do ano y (null = não atendido). */
  function turmaDe(anoLetivo, y, m, d = 1) {
    const idade = idadeNoCorte(anoLetivo, y, m, d);
    if (idade < 0 || idade > IDADE_MAX) return null;
    if (idade === 0) {
      const ok = y === anoLetivo - 1 && m > CORTE_MES && m <= BERCARIO_ULTIMO_MES;
      return ok ? TURMAS[0] : null;
    }
    return TURMAS.find((t) => t.idade === idade) || null;
  }

  /** Anos de nascimento exibidos: do ano anterior ao letivo até o da última turma. */
  function anosNascimento(anoLetivo) {
    const lista = [];
    for (let y = anoLetivo - 1; y >= anoLetivo - IDADE_MAX - 1; y--) lista.push(y);
    return lista;
  }

  const textoRegra = () =>
    `Para o ano letivo ${anoSelecionado}, a criança entra na turma da idade que completa até ${dataCorte}/${anoSelecionado}.`;

  const textoNota = () =>
    `Leia assim: encontre o mês e o ano de nascimento da criança e veja a turma em ${anoSelecionado}. ` +
    `A linha mais grossa entre março e abril marca a data de corte (${dataCorte}). ` +
    `Berçário: nascidos de abril a ${MESES[BERCARIO_ULTIMO_MES - 1].toLowerCase()} de ${anoSelecionado - 1}.`;

  /* ---------- Renderização ---------- */

  function renderAnos() {
    const dif = anoSelecionado - anoAtual();
    $("ce-ano-titulo").textContent = anoSelecionado;
    $("ce-ano-legenda").textContent =
      dif === 0 ? "ano letivo atual" :
      dif === 1 ? "próximo ano letivo" :
      dif === -1 ? "ano letivo anterior" :
      dif > 0 ? `daqui a ${dif} anos` : `há ${-dif} anos`;

    const padrao = anoPadrao();
    const voltar = $("ce-voltar");
    voltar.hidden = anoSelecionado === padrao;
    voltar.textContent = `Voltar a ${padrao}`;
  }

  function renderTabela() {
    const anos = anosNascimento(anoSelecionado);
    let html = `<colgroup><col class="ce-c-mes">${anos.map(() => "<col>").join("")}</colgroup>`;
    html += `<thead><tr><th class="ce-canto" rowspan="2" scope="col">Mês de<br>nascimento</th>` +
            `<th colspan="${anos.length}" scope="colgroup">Ano de nascimento</th></tr><tr>` +
            anos.map((y) => `<th scope="col">${y}</th>`).join("") + `</tr></thead><tbody>`;

    MESES.forEach((nomeMes, i) => {
      const m = i + 1;
      html += `<tr${m === CORTE_MES + 1 ? ' class="ce-pos-corte"' : ""}><th scope="row">${nomeMes}</th>`;
      for (const y of anos) {
        const turma = turmaDe(anoSelecionado, y, m);
        html += turma ? `<td class="ce-t${turma.idade}">${turma.nome}</td>` : `<td class="ce-nao">Não</td>`;
      }
      html += "</tr>";
    });
    $("ce-tabela").innerHTML = html + "</tbody>";
  }

  function renderLegenda() {
    $("ce-legenda").innerHTML = TURMAS
      .map((t) => `<li><i style="background:var(--ce-t${t.idade})"></i>${t.nome}</li>`)
      .join("") + `<li><i style="background:var(--ce-nao)"></i>Não atendido</li>`;
    $("ce-nota").textContent = textoNota();
  }

  function renderTudo() {
    $("ce-regra").textContent = textoRegra();
    renderAnos();
    renderLegenda();
    renderTabela();
  }

  function mudarAno(delta) {
    anoSelecionado += delta;
    renderTudo();
  }

  /* ---------- Exportar PDF (paisagem, download direto) ---------- */
  // Usa a jsPDF (static/js/vendor/jspdf.umd.min.js). O PDF sai sempre com as
  // cores do tema claro, qualquer que seja o tema ativo na tela.

  const hexParaRgb = (hex) => {
    const h = hex.trim().replace("#", "");
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  };

  /** Lê as cores das células do tema claro num elemento temporário forçado ao claro. */
  function coresDasCelulasClaras() {
    const tmp = document.createElement("div");
    tmp.className = "ce-paleta ce-forcar-claro";
    tmp.style.display = "none";
    document.body.appendChild(tmp);
    const cs = getComputedStyle(tmp);
    const v = (nome) => hexParaRgb(cs.getPropertyValue(nome));
    const cores = {
      nao: v("--ce-nao"), naoTinta: v("--ce-nao-tinta"), celula: v("--ce-celula-tinta"),
      turmas: TURMAS.map((t) => v(`--ce-t${t.idade}`)),
    };
    tmp.remove();
    return cores;
  }

  // Cores fixas da faixa e do cabeçalho do PDF (tema claro do protótipo)
  const PDF = {
    faixa: [243, 227, 160], faixaTinta: [58, 52, 24], sombra: [220, 203, 132],
    cab1: [74, 71, 120], cab2: [106, 103, 160], cabTinta: [246, 244, 251],
    superficie: [255, 254, 252], tinta: [43, 43, 58], suave: [106, 104, 128], linha: [227, 223, 232],
  };

  function exportarPDF() {
    if (!window.jspdf) {
      alert("Biblioteca de PDF não encontrada (static/js/vendor/jspdf.umd.min.js).");
      return;
    }
    const { jsPDF } = window.jspdf;
    const c = Object.assign({}, PDF, coresDasCelulasClaras());
    const doc = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4" });
    const W = doc.internal.pageSize.getWidth(); // 297
    const M = 10;
    const cor = (rgb) => doc.setFillColor(...rgb);
    const txt = (rgb) => doc.setTextColor(...rgb);

    /* faixa do título */
    const topoH = 24;
    cor(c.sombra); doc.roundedRect(M, M + 1.2, W - 2 * M, topoH, 4, 4, "F");
    cor(c.faixa);  doc.roundedRect(M, M, W - 2 * M, topoH, 4, 4, "F");
    txt(c.faixaTinta);
    doc.setFont("helvetica", "bold"); doc.setFontSize(22);
    doc.text(`CORTE ETÁRIO MATRÍCULAS - ${anoSelecionado}`, W / 2, M + 11.5, { align: "center" });
    doc.setFont("helvetica", "normal"); doc.setFontSize(10);
    doc.text(doc.splitTextToSize(textoRegra(), W - 2 * M - 20), W / 2, M + 18, { align: "center" });

    /* tabela */
    const anos = anosNascimento(anoSelecionado);
    const x0 = M, y0 = M + topoH + 7;
    const colMes = 32;
    const colW = (W - 2 * M - colMes) / anos.length;
    const rowH = 9, hdrH = 8;

    cor(c.cab1); doc.rect(x0, y0, colMes, hdrH * 2, "F");
    doc.rect(x0 + colMes, y0, colW * anos.length, hdrH, "F");
    cor(c.cab2); doc.rect(x0 + colMes, y0 + hdrH, colW * anos.length, hdrH, "F");
    txt(c.cabTinta); doc.setFont("helvetica", "bold");
    doc.setFontSize(9);
    doc.text("MÊS DE", x0 + 3, y0 + 6.2);
    doc.text("NASCIMENTO", x0 + 3, y0 + 11.2);
    doc.setFontSize(10);
    doc.text("ANO DE NASCIMENTO", x0 + colMes + (colW * anos.length) / 2, y0 + 5.6, { align: "center" });
    doc.setFontSize(11);
    anos.forEach((y, i) => doc.text(String(y), x0 + colMes + colW * i + colW / 2, y0 + hdrH + 5.6, { align: "center" }));

    const yCorpo = y0 + hdrH * 2;
    doc.setLineWidth(0.4);
    MESES.forEach((nomeMes, i) => {
      const m = i + 1;
      const y = yCorpo + rowH * i;
      cor(c.superficie); doc.rect(x0, y, colMes, rowH, "F");
      txt(c.tinta); doc.setFont("helvetica", "bold"); doc.setFontSize(9.5);
      doc.text(nomeMes.toUpperCase(), x0 + 3, y + 6);
      anos.forEach((ano, j) => {
        const turma = turmaDe(anoSelecionado, ano, m);
        const x = x0 + colMes + colW * j;
        cor(turma ? c.turmas[turma.idade] : c.nao);
        doc.setDrawColor(...c.superficie);
        doc.rect(x, y, colW, rowH, "FD");
        if (turma) { txt(c.celula); doc.setFont("helvetica", "bold"); }
        else       { txt(c.naoTinta); doc.setFont("helvetica", "normal"); }
        doc.setFontSize(8.5);
        doc.text((turma ? turma.nome : "Não").toUpperCase(), x + colW / 2, y + 5.8, { align: "center" });
      });
    });

    /* moldura e linha do corte (entre março e abril) */
    const yFim = yCorpo + rowH * 12;
    doc.setDrawColor(...c.cab1);
    doc.setLineWidth(0.8);
    doc.rect(x0, y0, W - 2 * M, yFim - y0);
    doc.line(x0 + colMes, y0 + hdrH * 2, x0 + colMes, yFim);
    doc.setLineWidth(1);
    const yCorte = yCorpo + rowH * CORTE_MES;
    doc.line(x0, yCorte, W - M, yCorte);

    /* legenda */
    let lx = x0, ly = yFim + 8;
    doc.setFont("helvetica", "normal"); doc.setFontSize(8.5);
    const itens = TURMAS.map((t) => ({ nome: t.nome, rgb: c.turmas[t.idade] }))
      .concat([{ nome: "Não atendido", rgb: c.nao }]);
    itens.forEach((it) => {
      const w = doc.getTextWidth(it.nome) + 11;
      if (lx + w > W - M) { lx = x0; ly += 6.5; }
      cor(it.rgb); doc.setDrawColor(...c.linha); doc.setLineWidth(0.2);
      doc.circle(lx + 2.5, ly - 1, 2.2, "FD");
      txt(c.tinta); doc.text(it.nome, lx + 6.5, ly);
      lx += w + 2;
    });

    /* nota */
    txt(c.suave); doc.setFontSize(8.5);
    doc.text(doc.splitTextToSize(textoNota(), W - 2 * M), x0, ly + 8);

    doc.save(`corte-etario-matriculas-${anoSelecionado}.pdf`);
  }

  /* ---------- Eventos ---------- */

  function telaAtiva() {
    return $("sec-corte-etario").classList.contains("active");
  }

  function init() {
    $("ce-anterior").addEventListener("click", () => mudarAno(-1));
    $("ce-proximo").addEventListener("click", () => mudarAno(1));
    $("ce-voltar").addEventListener("click", () => { anoSelecionado = anoPadrao(); renderTudo(); });
    $("ce-exportar").addEventListener("click", exportarPDF);

    // Setas ← → trocam o ano, mas só com esta tela aberta e fora de campos de texto
    document.addEventListener("keydown", (e) => {
      if (!telaAtiva() || e.altKey || e.ctrlKey || e.metaKey) return;
      const alvo = e.target;
      if (alvo && (alvo.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName))) return;
      if (e.key === "ArrowLeft") mudarAno(-1);
      if (e.key === "ArrowRight") mudarAno(1);
    });
  }

  /** Chamada por irPara("corte-etario"): sempre abre no ano letivo padrão. */
  window.carregarCorteEtario = function () {
    anoSelecionado = anoPadrao();
    renderTudo();
  };

  init();
})();
