/* "Quem já recebeu" (tela Mandar avisos) e "Fila de envio" (tela WhatsApp) no jsdom. Rodar: cd tests/js && npm install jsdom && node teste_enviados_e_fila.js */
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const RAIZ = path.join(__dirname, "..", "..", "src", "web");
const ler = (...p) => fs.readFileSync(path.join(RAIZ, ...p), "utf-8");
const esperar = (ms = 30) => new Promise((r) => setTimeout(r, ms));
let falhas = 0;
const ok = (cond, msg) => { console.log((cond ? "  ok   " : "  FALHA ") + msg); if (!cond) falhas++; };
const resp = (j, status = 200) => ({ ok: status < 400, status, json: async () => j });

async function testeEnviados() {
  console.log("# quem já recebeu");
  const dom = new JSDOM(`<body><div id="toast"><span id="toast-msg"></span></div><div id="x"></div></body>`, { runScripts: "dangerously", url: "http://localhost/" });
  const w = dom.window;
  let abriu = 0;
  w.fetch = async (url) => {
    if (url.endsWith("/avisos/enviados")) {
      abriu++;
      return resp({ total: 2, por_publico: {}, envios: [
        { para: "ana@pg.gov.br", nome: "Escola <b>Ana</b>", aluno: "ANA LIMA", cgm: "10", assunto: "Transferência", enviado_em: "2026-11-02T10:00:00", publico: "destino", anexos: ["g.pdf"] },
        { para: "mae@x.com", nome: "MARIA", aluno: "BETO", cgm: "", assunto: "Vaga", enviado_em: "2026-11-01T09:00:00", publico: "pais", anexos: [] }] });
    }
    return resp({});
  };
  for (const arq of ["icons.js", "app.js"]) {
    const sc = w.document.createElement("script"); sc.textContent = ler("static", "js", arq); w.document.body.appendChild(sc);
  }
  await esperar(100);
  w.document.getElementById("x").innerHTML = w.eval(`campoHTML({tipo:"enviados_registro",id:"campo-enviados",nome:"enviados_registro",label:"Quem já recebeu",descricao:"d"})`);
  w.eval("inicializarCampoEnviados()");
  const $ = (id) => w.document.getElementById(id);
  ok($("campo-enviados-painel").style.display === "none" && abriu === 0, "começa fechado e não lê nada");
  $("campo-enviados-ver").click(); await esperar();
  ok($("campo-enviados-painel").style.display !== "none" && abriu === 1, "abrir carrega o registro");
  ok($("campo-enviados-resumo").textContent.includes("2 de 2"), "resumo: " + $("campo-enviados-resumo").textContent);
  ok(!$("campo-enviados-lista").innerHTML.includes("<b>Ana"), "nome com HTML é escapado");
  ok($("campo-enviados-lista").textContent.includes("escola de destino") && $("campo-enviados-lista").textContent.includes("responsável"), "mostra o público");
  $("campo-enviados-busca").value = "maria"; $("campo-enviados-busca").dispatchEvent(new w.Event("input"));
  ok($("campo-enviados-lista").querySelectorAll(".checklist-item").length === 1 && $("campo-enviados-resumo").textContent.includes("1 de 2"), "busca filtra sem acento/caixa");
  $("campo-enviados-busca").value = "zzz"; $("campo-enviados-busca").dispatchEvent(new w.Event("input"));
  ok($("campo-enviados-lista").children.length === 0, "busca sem resultado esvazia a lista");
  $("campo-enviados-atualizar").click(); await esperar();
  ok(abriu === 2, "Atualizar lê de novo");
  $("campo-enviados-ver").click();
  ok($("campo-enviados-painel").style.display === "none", "Esconder fecha o painel");
}

async function testeFila() {
  console.log("# fila do WhatsApp");
  const estadoFila = (extra = {}) => ({
    estado: "parada", mensagem: "", config: { intervalo_s: 45, limite_diario: 40, continuar_no_dia_seguinte: true },
    contagem: { pendente: 2, enviado: 0, simulado: 0, falhou: 1, cancelado: 0, enviando: 0 }, enviados_hoje: 3, restante_hoje: 37,
    itens: [
      { id: "a1", nome: "Ana <i>Pai</i>", numero: "55 42 *****-**11", texto: "Oi", status: "pendente", erro: "", enviado_em: "" },
      { id: "b2", nome: "Beto", numero: "55 42 *****-**22", texto: "Oi 2", status: "pendente", erro: "", enviado_em: "" },
      { id: "c3", nome: "Caio", numero: "55 42 *****-**33", texto: "Oi 3", status: "falhou", erro: "sem rede", enviado_em: "" }], ...extra });
  const chamadas = [];
  let confirma = true;
  const html = `<body><div id="toast"><span id="toast-msg"></span></div>${ler("templates", "whatsapp.html")}
    <script>window.__t=[];function toast(m){window.__t.push(m)}</script><script>${ler("static", "js", "whatsapp.js").replace(/<\/script>/g, "<\\/script>")}</script></body>`;
  const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/", beforeParse(w) {
    w.confirm = () => confirma; w.prompt = () => "Meu modelo";
    w.fetch = async (url, op = {}) => {
      const metodo = op.method || "GET"; chamadas.push([metodo, url, op.body]);
      if (url.endsWith("/status")) return resp({ situacao: "conectado", simulado: false, provedor: "blake", mensagem: "", tem_sessao: true });
      if (url.endsWith("/fila") || url.endsWith("/fila/pausar")) return resp(estadoFila());
      if (url.endsWith("/fila/iniciar")) return resp(estadoFila({ estado: "rodando", mensagem_acao: "Fila iniciada." }));
      if (url.endsWith("/fila/itens") && metodo === "POST") return resp({ ...estadoFila(), resultado: { adicionados: 1, duplicados: 0, invalidos: [] } });
      if (url.endsWith("/fila/config")) return resp(estadoFila());
      if (url.endsWith("/fila/modelos")) return resp({ modelos: [{ id: "livre", nome: "Livre", texto: "", padrao: true, personalizado: false }, { id: "chamada", nome: "Chamada", texto: "Olá $ALUNO", padrao: true, personalizado: false }], marcadores: ["ALUNO"] });
      if (url.endsWith("/fila/prematricula")) return resp({ alunos: [{ id: "111", nome: "ANA", turma: "T1", posicao: 1, tem_telefone: true }, { id: "112", nome: "BETO", turma: "T1", posicao: 2, tem_telefone: false }] });
      if (url.endsWith("/fila/da-prematricula")) return resp({ ...estadoFila(), resultado: { adicionados: 1, duplicados: 0, invalidos: [], sem_telefone: [] } });
      if (url.includes("/fila/itens/") && url.endsWith("/cancelar")) return resp(estadoFila());
      return resp({});
    };
    w.HTMLElement.prototype.scrollIntoView = () => {};
  } });
  const w = dom.window, $ = (id) => w.document.getElementById(id);
  w.document.dispatchEvent(new w.Event("DOMContentLoaded"));
  w.carregarWhatsapp(); await esperar(80);
  w.pararWhatsapp();
  ok($("wa-fila-badge").textContent === "Parada", "badge: " + $("wa-fila-badge").textContent);
  ok($("wa-fila-resumo").textContent.includes("3 de 40") && $("wa-fila-resumo").textContent.includes("2 pendente"), "resumo do dia e contagem");
  ok($("wa-fila-lista").querySelectorAll(".checklist-item").length === 3 && !$("wa-fila-lista").innerHTML.includes("<i>Pai"), "lista com 3 itens e nome escapado");
  ok($("wa-fila-intervalo").value === "45" && $("wa-fila-limite").value === "40" && $("wa-fila-amanha").checked, "ajustes carregados");
  ok($("wa-fila-modelo").options.length === 2 && $("wa-fila-pm-modelo").options.length === 2 && $("wa-fila-pm-modelo").options[0].value === "comunicado", "modelos nos dois seletores (só os com texto + comunicado no da pré-matrícula)");

  $("wa-fila-iniciar").click(); await esperar();
  ok(!chamadas.some((c) => c[1].endsWith("/fila/iniciar")) && w.__t.some((t) => t.includes("confirmação")), "envio real exige a caixa de confirmação");
  $("wa-fila-confirmo").checked = true; $("wa-fila-iniciar").click(); await esperar();
  const ini = chamadas.find((c) => c[1].endsWith("/fila/iniciar"));
  ok(ini && JSON.parse(ini[2]).confirmo === true && $("wa-fila-badge").textContent === "Enviando", "iniciar manda a confirmação e mostra Enviando");
  ok($("wa-fila-iniciar").disabled && !$("wa-fila-pausar").disabled, "enquanto envia: Iniciar desligado, Pausar ligado");

  $("wa-fila-lista").querySelector("[data-fila-acao='cancelar']").click(); await esperar();
  ok(chamadas.some((c) => c[1].endsWith("/fila/itens/a1/cancelar") && c[0] === "POST"), "cancelar item chama a rota certa");

  $("wa-fila-numero").value = "42999991111"; $("wa-fila-nome").value = "Ana"; $("wa-fila-texto").value = "Oi";
  $("wa-fila-por").click(); await esperar();
  const add = chamadas.find((c) => c[1].endsWith("/fila/itens") && c[0] === "POST");
  ok(add && JSON.parse(add[2]).itens[0].numero === "42999991111" && $("wa-fila-numero").value === "", "pôr na fila envia e limpa o formulário");

  $("wa-fila-modelo").value = "chamada"; $("wa-fila-modelo").dispatchEvent(new w.Event("change"));
  ok($("wa-fila-texto").value === "Olá $ALUNO", "escolher modelo preenche o texto");

  $("wa-fila-pm-carregar").click(); await esperar();
  ok($("wa-fila-pm-lista").querySelectorAll("input").length === 2 && $("wa-fila-pm-lista").querySelector("input[disabled]"), "pré-matrícula: sem telefone fica desabilitado");
  $("wa-fila-pm-todos").click(); $("wa-fila-pm-por").click(); await esperar();
  const pm = chamadas.find((c) => c[1].endsWith("/fila/da-prematricula"));
  ok(pm && JSON.stringify(JSON.parse(pm[2]).ids) === '["111"]' && JSON.parse(pm[2]).modelo_id === "comunicado", "manda só os marcados e o modelo escolhido");

  $("wa-fila-limite").value = "10"; $("wa-fila-salvar-config").click(); await esperar();
  const cfg = chamadas.find((c) => c[1].endsWith("/fila/config"));
  ok(cfg && JSON.parse(cfg[2]).limite_diario === "10", "salvar ajustes manda o limite");

  $("wa-fila-filtro").value = "enviado"; $("wa-fila-filtro").dispatchEvent(new w.Event("change"));
  ok($("wa-fila-lista").textContent.includes("Nada para mostrar"), "filtro 'Enviadas' sem itens mostra aviso");
}

(async () => {
  await testeEnviados();
  await testeFila();
  console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTUDO OK");
  process.exit(falhas ? 1 : 0);
})().catch((e) => { console.log("ERRO:", e.stack); process.exit(1); });
