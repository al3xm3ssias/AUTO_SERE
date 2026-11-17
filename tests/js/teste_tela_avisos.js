/* Teste da tela "Mandar avisos" no jsdom (sem navegador): select pesquisável de unidades, tipo de mensagem, modelos, payload.
   Rodar:  cd tests/js && npm install jsdom && python ../../tests/js/gerar_dados.py && node teste_tela_avisos.js
   (o tests/test_ui_avisos_js.py faz isso sozinho quando existir node e jsdom). */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const D = JSON.parse(fs.readFileSync(process.argv[2] || path.join(__dirname, "dados.json"), "utf-8"));
const JS = path.join(__dirname, "..", "..", "src", "web", "static", "js");
const dom = new JSDOM(`<body><div id="toast"><span id="toast-msg"></span></div><div id="campos-automacao"></div><button id="btn-executar-tarefa">Executar</button></body>`,
  { runScripts: "dangerously", url: "http://localhost/" });
const w = dom.window;
const chamadas = []; let salvou = false; let confirmaResp = true; let promptResp = "Meu modelo";
w.fetch = async (url, op = {}) => {
  const metodo = op.method || "GET"; chamadas.push([metodo, url, op.body]);
  const ok = (j, status = 200) => ({ ok: status < 400, status, json: async () => j });
  if (url.endsWith("/componentes")) return ok(salvou ? D.info2 : D.info);
  if (url.endsWith("/avisos/unidades")) return ok({ unidades: D.unidades });
  if (url.endsWith("/avisos/exemplo")) {
    const corpo = JSON.parse(op.body || "{}");
    if (!corpo.assunto && !corpo.mensagem) return ok({ vazio: true });
    if ((corpo.alunos || "").includes('"118"')) return ok({ para: "", nome: "ESCOLA MUNICIPAL ANA NERI", assunto: "Transferência de HUGO", corpo: "Aluno HUGO MELO <b>x</b>", aluno: "HUGO MELO", total: 0, aviso: "Nenhum aluno novo com escola de origem e e-mail" });
    return ok({ para: "ana@pg.gov.br", nome: "Escola Municipal Ana Néri", assunto: "Transferência de ANA LIMA", corpo: "Aluno ANA LIMA, CGM 1000000001, série 5º ano", aluno: "ANA LIMA", total: 2 });
  }
  if (url.includes("/avisos/alunos")) {
    const f = new URL("http://x" + url).searchParams.get("fonte");
    if (f === "proximo") return ok({ alunos: [], aviso: "Ainda não existe previsao_alunos_2027.json" });
    return ok({ alunos: [
      { id: "111", nome: "ANA LIMA", turma: "Infantil IV", fonte: "ano", estado: "ok", cgm: "1000000001", escola_origem: "ESCOLA MUNICIPAL ANA NERI", motivo: "" },
      { id: "112", nome: "BETO <i>LIMA</i>", turma: "1º Ano", fonte: "ano", estado: "sem_vinculo", cgm: "", escola_origem: "", motivo: "" },
      { id: "118", nome: "HUGO MELO", turma: "1º Ano", fonte: "ano", estado: "verificar", cgm: "", escola_origem: "X", motivo: "sem linha de 2026" }] });
  }
  if (url.endsWith("/previa")) return ok({ texto: "prévia", aviso: false });
  if (url.endsWith("/avisos/modelos") && metodo === "POST") { salvou = true; return ok({ modelo: { id: "meu-modelo", nome: "Meu modelo" }, modelos: [] }); }
  if (url.includes("/avisos/modelos/") && metodo === "DELETE") { return ok({ acao: "excluido", modelos: [] }); }
  return ok({});
};
w.confirm = () => confirmaResp; w.prompt = () => promptResp;
w.HTMLElement.prototype.scrollIntoView = () => {};
const erros = []; w.addEventListener("error", (e) => erros.push(e.message));
for (const arq of ["icons.js", "app.js"]) {          // como <script> clássico: let/const de topo ficam no escopo global, como no navegador
  const sc = w.document.createElement("script");
  sc.textContent = fs.readFileSync(path.join(JS, arq), "utf-8");
  w.document.body.appendChild(sc);
}
const esperar = (ms = 30) => new Promise((r) => setTimeout(r, ms));
const $ = (id) => w.document.getElementById(id);
let falhas = 0;
const ok = (cond, msg) => { console.log((cond ? "  ok   " : "  FALHA ") + msg); if (!cond) falhas++; };
const mudar = (el, valor) => { el.value = valor; el.dispatchEvent(new w.Event("change", { bubbles: true })); };
const marcar = (cx, v) => { cx.checked = v; cx.dispatchEvent(new w.Event("change", { bubbles: true })); };

(async () => {
  await esperar(100);                                 // deixa o DOMContentLoaded do app rodar antes de contar os erros
  const errosDoCarregamento = erros.length;          // o DOM de teste é mínimo: initTema reclama dos botões de tema, que não são desta tela
  w.eval('automacaoAtual = "avisos"');
  try { await w.eval('renderizarCamposAutomacao("avisos")'); } catch (e) { console.log("ERRO render:", e.stack.split("\n").slice(0,4).join(" | ")); }
  await esperar();
  if (!$("campo-unidades-busca")) console.log("HTML:", $("campos-automacao").innerHTML.slice(0, 300), "| chamadas:", JSON.stringify(chamadas.slice(0,4)), "| erros:", erros.slice(0,3));

  console.log("# campos montados");
  ok(!!$("campo-unidades-busca") && !!$("campo-unidades-lista"), "busca e lista de unidades existem");
  ok($("campo-unidades").value === "[]" && $("campo-unidades").style.display === "none", "valor oculto começa [] (= todas)");
  const linhas = () => [...$("campo-unidades-lista").querySelectorAll("label")].map((l) => l.textContent.replace(/\s+/g, " ").trim());
  ok(linhas().length === 3 + 4, "3 grupos + 4 unidades: " + linhas().length);
  ok(linhas().some((l) => l.includes("CMEI") && l.includes("Pequeno")), "CMEI aparece com a marca CMEI");
  ok(linhas().some((l) => l.includes("Sem Email") && l.includes("sem e-mail")), "unidade sem e-mail é sinalizada");
  ok(!$("campo-unidades-lista").innerHTML.includes("<b>Perigosa"), "nome com HTML é escapado na lista");
  ok($("campo-unidades-resumo").textContent.includes("todas"), "resumo: nenhuma marcada = todas");
  ok(!$("campo-email-teste") && !$("campo-filtro-nome"), "campos removidos não existem (e-mail de teste, filtro por nome)");
  ok($("campo-assunto").placeholder === "", "assunto sem texto de exemplo");
  ok(!!$("campo-intervalo") && !!$("campo-limite-lote"), "pausa e limite existem");
  const vis = (id) => $(id).closest(".field").style.display !== "none";
  ok(!vis("campo-intervalo") && !vis("campo-limite-lote"), "pausa/limite escondidos fora do modo enviar");
  ok(!vis("campo-unidades"), "unidades escondidas sem escolher 'Para quem'");

  console.log("# para quem = escolas mostra unidades");
  mudar($("campo-publico"), "escolas"); await esperar();
  ok(vis("campo-unidades") && vis("campo-situacao-pais") && vis("campo-fonte-alunos"), "unidades, alunos novos e fonte aparecem");
  mudar($("campo-modo-aviso"), "enviar"); await esperar();
  ok(vis("campo-intervalo") && vis("campo-limite-lote"), "pausa e limite aparecem no modo enviar");
  mudar($("campo-modo-aviso"), "simular");

  console.log("# busca e seleção de unidades");
  $("campo-unidades-busca").value = "ANA"; $("campo-unidades-busca").dispatchEvent(new w.Event("input"));
  ok(linhas().length === 1 && linhas()[0].includes("Ana Néri"), "busca sem acento/caixa acha só a Ana Néri: " + JSON.stringify(linhas()));
  marcar($("campo-unidades-lista").querySelector("input"), true);
  ok($("campo-unidades").value === '["Escola Municipal Ana Néri"]', "marcar vira lista JSON: " + $("campo-unidades").value);
  $("campo-unidades-busca").value = ""; $("campo-unidades-busca").dispatchEvent(new w.Event("input"));
  const cx = (rotulo) => [...$("campo-unidades-lista").querySelectorAll("label")].find((l) => l.textContent.includes(rotulo)).querySelector("input");
  ok(cx("Ana Néri").checked && !cx("Todos os CMEIs").checked, "marcação sobrevive à busca");
  marcar(cx("Todos os CMEIs"), true);
  ok($("campo-unidades").value === '["Escola Municipal Ana Néri","@cmeis"]', "unidade + grupo: " + $("campo-unidades").value);
  marcar(cx("Todas as escolas e CMEIs"), true);
  ok($("campo-unidades").value === "[]", "marcar 'Todas' limpa as outras");
  marcar(cx("Ana Néri"), true); marcar(cx("Ana Néri"), false);
  ok($("campo-unidades").value === "[]" && cx("Todas as escolas e CMEIs").checked, "desmarcar tudo volta para 'Todas'");
  marcar(cx("Ana Néri"), true);

  console.log("# quais alunos (lista com estado do vínculo)");
  const alunosLinhas = () => [...$("campo-alunos-lista").querySelectorAll("label")].map((l) => l.textContent.replace(/\s+/g, " ").trim());
  ok(alunosLinhas().length === 3, "3 alunos listados: " + JSON.stringify(alunosLinhas()));
  ok(alunosLinhas()[0].includes("CGM 1000000001") && alunosLinhas()[0].includes("ANA NERI"), "aluno com vínculo ok mostra o CGM e a escola de origem");
  ok(alunosLinhas()[1].includes("sem vínculo da Base ABC"), "aluno sem vínculo é sinalizado");
  ok(alunosLinhas()[2].includes("vínculo a verificar: sem linha de 2026"), "vínculo a verificar mostra o motivo");
  ok(!$("campo-alunos-lista").innerHTML.includes("<i>LIMA"), "nome com HTML é escapado");
  ok($("campo-alunos").value === "[]" && $("campo-alunos-resumo").textContent.includes("todos (3)"), "nada marcado = todos");
  $("campo-alunos-marcar-ok").click(); await esperar();
  ok($("campo-alunos").value === '["111"]', "'Marcar quem tem CGM ok' marca só o aluno ok: " + $("campo-alunos").value);
  marcar($("campo-alunos-lista").querySelectorAll("input")[1], true);
  ok($("campo-alunos").value === '["111","112"]', "marcar mais um aluno: " + $("campo-alunos").value);
  $("campo-alunos-busca").value = "hugo"; $("campo-alunos-busca").dispatchEvent(new w.Event("input"));
  ok(alunosLinhas().length === 1 && alunosLinhas()[0].includes("HUGO"), "busca de aluno");
  $("campo-alunos-busca").value = ""; $("campo-alunos-busca").dispatchEvent(new w.Event("input"));
  chamadas.length = 0; mudar($("campo-fonte-alunos"), "proximo"); await esperar(60);
  ok(chamadas.some((c) => c[1].includes("/avisos/alunos") && c[1].includes("fonte=proximo") && c[1].includes("situacao=matriculados")), "trocar a fonte recarrega a lista");
  ok($("campo-alunos-lista").textContent.includes("previsao_alunos_2027.json") && $("campo-alunos").value === "[]", "fonte sem arquivo: mostra o aviso e descarta as marcações que sumiram");
  mudar($("campo-fonte-alunos"), "ambas"); await esperar(60);
  $("campo-alunos-limpar").click();
  ok($("campo-alunos").value === "[]", "Limpar desmarca tudo");
  marcar($("campo-alunos-lista").querySelectorAll("input")[0], true);

  console.log("# tipo de mensagem carrega o texto");
  const tipo = $("campo-tipo-mensagem");
  ok([...tipo.options].map((o) => o.value).join() === "livre,transferencia", "opções: " + [...tipo.options].map((o) => o.value));
  mudar($("campo-publico"), "pais");
  mudar(tipo, "transferencia"); await esperar();
  ok($("campo-assunto").value.includes("$ALUNO"), "assunto carregado: " + $("campo-assunto").value);
  ok($("campo-mensagem").value.includes("$CGM") && $("campo-mensagem").value.includes("SME"), "mensagem carregada");
  ok($("campo-publico").value === "escolas", "o tipo ajusta 'Para quem' para escolas");
  $("campo-mensagem").value = "meu texto"; mudar(tipo, "livre");
  ok($("campo-mensagem").value === "meu texto", "tipo 'livre' não apaga o que foi digitado");

  console.log("# como fica a mensagem (texto do aluno)");
  const exemplo = () => $("exemplo-mensagem").textContent;
  ok(!!$("exemplo-mensagem"), "caixa 'Como fica a mensagem' existe");
  mudar(tipo, "transferencia"); await esperar(500);
  ok(exemplo().includes("Para: Escola Municipal Ana Néri <ana@pg.gov.br> — aluno ANA LIMA (1º de 2)"), "mostra para quem e de qual aluno: " + exemplo().slice(0, 90));
  ok(exemplo().includes("Assunto: Transferência de ANA LIMA") && exemplo().includes("CGM 1000000001"), "assunto e corpo já preenchidos com o aluno");
  $("campo-alunos-limpar").click();
  marcar($("campo-alunos-lista").querySelectorAll("input")[2], true); await esperar(500);
  ok(exemplo().includes("⚠️ Nenhum aluno novo com escola de origem e e-mail") && exemplo().includes("aluno HUGO MELO"), "aluno que não receberia: mostra o aviso e o texto dele");
  ok(!$("exemplo-mensagem").innerHTML.includes("<b>x</b>"), "texto do exemplo é inserido como texto, não como HTML");
  $("campo-assunto").value = ""; $("campo-mensagem").value = ""; $("campo-assunto").dispatchEvent(new w.Event("input")); await esperar(500);
  ok(exemplo().includes("Escolha um tipo de mensagem"), "sem texto: orienta a escolher um tipo");
  $("campo-alunos-limpar").click(); marcar($("campo-alunos-lista").querySelectorAll("input")[0], true);
  mudar(tipo, "transferencia"); mudar(tipo, "livre"); await esperar(100);

  console.log("# payload");
  const p = w.eval("_execMontarPayload()");
  ok(p.unidades === '["Escola Municipal Ana Néri"]' && p.publico === "escolas" && p.modo === "simular" && p.tipo_mensagem === "livre", "payload: " + JSON.stringify({u: p.unidades, p: p.publico, m: p.modo, t: p.tipo_mensagem}));
  ok(p.fonte === "ambas" && p.intervalo_s === "10" && p.limite_lote === "50", "fonte/pausa/limite no payload");
  ok(p.alunos === '["111"]', "alunos marcados no payload: " + p.alunos);
  ok(!("email_teste" in p) && !("filtro_nome" in p), "sem e-mail de teste nem filtro no payload");

  console.log("# confirmação só no modo enviar");
  const decide = (modo) => w.eval(`(() => { const cq = _infoComponentes.confirmar_quando; const payload = {modo: "${modo}"}; return cq ? payload[cq.campo] === cq.valor : false; })()`);
  ok(decide("enviar") === true && decide("simular") === false && decide("teste") === false, "pede confirmação só para 'enviar'");

  console.log("# salvar como modelo (novo)");
  $("campo-assunto").value = "Assunto novo"; $("campo-mensagem").value = "Texto novo $ALUNO";
  chamadas.length = 0; promptResp = "Meu modelo";
  $("btn-modelo-salvar").click(); await esperar(80);
  const post = chamadas.find((c) => c[0] === "POST" && c[1].endsWith("/avisos/modelos"));
  ok(!!post, "POST /avisos/modelos enviado");
  const corpo = post ? JSON.parse(post[2]) : {};
  ok(corpo.nome === "Meu modelo" && corpo.assunto === "Assunto novo" && corpo.publico === "escolas" && !corpo.id, "corpo: " + JSON.stringify(corpo));
  ok([...$("campo-tipo-mensagem").options].map((o) => o.value).includes("meu-modelo") && $("campo-tipo-mensagem").value === "meu-modelo", "tela recarregada com o modelo novo já escolhido");
  ok($("campo-assunto").value === "Assunto $ALUNO" && $("campo-publico").value === "pais", "modelo escolhido carrega o texto salvo e o público");

  console.log("# excluir modelo");
  chamadas.length = 0; confirmaResp = true;
  $("btn-modelo-excluir").click(); await esperar(80);
  ok(chamadas.some((c) => c[0] === "DELETE" && c[1].endsWith("/avisos/modelos/meu-modelo")), "DELETE do modelo personalizado");
  chamadas.length = 0; mudar($("campo-tipo-mensagem"), "livre");
  $("btn-modelo-excluir").click(); await esperar(40);
  ok(!chamadas.some((c) => c[0] === "DELETE"), "modelo pronto sem ajuste não chama DELETE");
  ok($("toast-msg").textContent.includes("prontos"), "avisa que os prontos não somem: " + $("toast-msg").textContent);

  console.log("# salvar sem texto");
  $("campo-assunto").value = ""; chamadas.length = 0;
  $("btn-modelo-salvar").click(); await esperar(40);
  ok(!chamadas.some((c) => c[0] === "POST"), "não salva modelo sem assunto/mensagem");

  ok(erros.length === errosDoCarregamento, "nenhum erro de JavaScript durante o uso da tela: " + erros.slice(errosDoCarregamento).join("|"));
  console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTUDO OK"); process.exit(falhas ? 1 : 0);
})().catch((e) => { console.log("EXCEÇÃO:", e.stack); process.exit(2); });
