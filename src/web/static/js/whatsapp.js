/* Tela WhatsApp — consulta /web/api/whatsapp/status enquanto a tela está aberta. */
(function () {
  const BASE = "/web/api/whatsapp";
  const $ = (id) => document.getElementById(id);
  let timer = null;
  let ultimoQrId = "";
  let estado = null;

  async function chamar(caminho, metodo = "GET", corpo = null) {
    const opts = { method: metodo, headers: { "Content-Type": "application/json" } };
    if (corpo !== null) opts.body = JSON.stringify(corpo);
    const res = await fetch(`${BASE}${caminho}`, opts);
    let dados = {};
    try { dados = await res.json(); } catch (e) { /* corpo vazio */ }
    return { ok: res.ok, status: res.status, dados };
  }

  const ROTULOS = {
    conectado: ["Conectado", "lime"], aguardando_qr: ["Aguardando QR", "amber"], iniciando: ["Iniciando…", "amber"],
    reconectando: ["Reconectando…", "amber"], desconectado: ["Desconectado", "rose"],
    gateway_offline: ["Gateway offline", "rose"], desconhecido: ["Não confirmado", "muted"],
    parado: ["Não iniciado", "muted"], verificando: ["Verificando…", "muted"], simulado: ["Simulado", "blue"], config_incompleta: ["Configuração incompleta", "rose"],
  };

  function pintarBadge(el, texto, cor) {
    el.textContent = texto;
    el.style.background = `var(--badge-${cor}-bg)`;
    el.style.border = `1px solid var(--badge-${cor}-brd)`;
    el.style.color = cor === "muted" ? "var(--txt2)" : `var(--${cor})`;
  }

  function mostrar(id, sim) { $(id).hidden = !sim; }

  function renderizar(s) {
    estado = s;
    const [rotulo, cor] = ROTULOS[s.situacao] || [s.situacao, "muted"];
    pintarBadge($("wa-badge"), rotulo, cor);
    $("wa-mensagem").textContent = s.mensagem || "";
    $("wa-gateway-url").textContent = s.gateway_url ? `Gateway: ${s.gateway_url}` : "";
    $("wa-cmd").textContent = s.comando_docker || "";

    const temSessao = !!s.tem_sessao, temGw = !!s.tem_gateway;
    const modo = s.provedor || s.provedor_configurado;
    mostrar("wa-bloco-simulado", s.simulado || s.provedor_configurado === "simulado");
    mostrar("wa-bloco-offline", temGw && s.situacao === "gateway_offline");
    mostrar("wa-bloco-parado", modo === "whatsplay" && s.situacao === "parado");
    $("wa-conectar").textContent = modo === "whatsplay" ? "Abrir o WhatsApp" : "Gerar QR Code";
    mostrar("wa-conectar", temSessao && !["conectado", "gateway_offline", "verificando", "iniciando"].includes(s.situacao));
    mostrar("wa-verificar", temGw && !["gateway_offline", "verificando"].includes(s.situacao));
    mostrar("wa-campo-verificar", temGw && ["desconhecido", "desconectado"].includes(s.situacao));
    mostrar("wa-ajuda-qr", temSessao && ["desconectado", "desconhecido", "parado"].includes(s.situacao));
    mostrar("wa-card-avancado", true);
    mostrar("wa-webhook-bloco", !!s.tem_webhook);
    mostrar("wa-desconectar", temSessao);
    $("wa-desconectar").textContent = modo === "whatsplay" ? "Fechar o WhatsApp" : "Desconectar este número";
    $("wa-desconectar-ajuda").textContent = modo === "whatsplay"
      ? "Fechar o WhatsApp só fecha o navegador deste computador; o vínculo com o celular continua."
      : "Desconectar encerra o login no gateway; para vincular outro número, zere o vínculo (docs/WHATSAPP.md).";
    $("wa-modo-atual").textContent = ({ whatsplay: "sem Docker (navegador)", blake: "gateway Docker", simulado: "simulado" })[modo] || modo;

    const temQr = s.situacao === "aguardando_qr" && !!s.qr_id;
    mostrar("wa-bloco-qr", temQr);
    if (temQr && s.qr_id !== ultimoQrId) {
      ultimoQrId = s.qr_id;
      $("wa-qr-img").src = `${BASE}/qr?id=${encodeURIComponent(s.qr_id)}`;
    }
    if (!temQr) ultimoQrId = "";

    pintarBadge($("wa-badge-envio"), s.envio_real ? "Envio real: permitido" : "Envio real: bloqueado", s.envio_real ? "amber" : "muted");
    $("wa-alternar-envio").textContent = s.envio_real ? "Bloquear envio real" : "Permitir envio real";
    mostrar("wa-linha-confirmo", !s.simulado);
  }

  async function atualizar() {
    atualizarFila();
    try {
      const r = await chamar("/status");
      if (r.ok) renderizar(r.dados);
    } catch (e) {
      renderizar({ situacao: "gateway_offline", mensagem: "Não consegui falar com o sistema.", comando_docker: "" });
    }
  }

  async function atualizarWebhook() {
    const r = await chamar("/webhooks");
    $("wa-webhook-estado").textContent = r.ok
      ? (r.dados.registrado ? "Webhook do sistema: registrado no gateway." : "Webhook do sistema: não registrado.")
      : (r.dados.erro || "Webhook indisponível.");
  }

  function iniciar() {
    pararWhatsapp();
    atualizar().then(() => { if (estado && estado.tem_webhook) atualizarWebhook(); });
    timer = setInterval(atualizar, 2500);
  }
  function pararWhatsapp() { if (timer) { clearInterval(timer); timer = null; } }
  window.carregarWhatsapp = iniciar;
  window.pararWhatsapp = pararWhatsapp;

  async function acao(caminho, corpo, aposOk) {
    const r = await chamar(caminho, "POST", corpo);
    toast(r.dados.mensagem || r.dados.erro || (r.ok ? "Feito." : "Falhou."));
    if (aposOk) await aposOk(r);
    atualizar();
    return r;
  }

  /* ───────────── Fila de envio (7b) ───────────── */
  let fila = null;
  let ultimaAssinaturaFila = "";
  let modelosFila = [];
  const esc = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const ROTULOS_FILA = {
    parada: ["Parada", "muted"], rodando: ["Enviando", "lime"], pausada: ["Pausada", "amber"],
    concluida: ["Concluída", "blue"], aguardando_dia: ["Aguardando o dia seguinte", "amber"],
  };
  const ROTULOS_ITEM = { pendente: "Pendente", enviando: "Enviando…", enviado: "Enviada", simulado: "Simulada", falhou: "Falhou", cancelado: "Cancelada" };

  async function chamarFila(caminho, metodo = "GET", corpo = null, avisar = true) {
    const r = await chamar(`/fila${caminho}`, metodo, corpo);
    if (!r.ok) { if (avisar) toast(r.dados.erro || "Não foi possível."); return null; }
    if (r.dados.itens) { fila = r.dados; ultimaAssinaturaFila = JSON.stringify(r.dados); desenharFila(); }
    return r.dados;
  }

  function desenharFila() {
    const f = fila;
    if (!f || !$("wa-fila-badge")) return;
    const [rotulo, cor] = ROTULOS_FILA[f.estado] || [f.estado, "muted"];
    pintarBadge($("wa-fila-badge"), rotulo, cor);
    $("wa-fila-msg").textContent = f.mensagem || "";
    const c = f.contagem;
    $("wa-fila-resumo").textContent = `Hoje: ${f.enviados_hoje} de ${f.config.limite_diario} enviadas (restam ${f.restante_hoje}). `
      + `Na fila: ${c.pendente} pendente(s) · ${c.enviado} enviada(s) · ${c.falhou} com falha · ${c.cancelado} cancelada(s)`
      + (c.simulado ? ` · ${c.simulado} simulada(s)` : "") + ".";
    const ativa = f.estado === "rodando" || f.estado === "aguardando_dia";
    $("wa-fila-iniciar").disabled = ativa || c.pendente === 0;
    $("wa-fila-iniciar").textContent = f.estado === "pausada" ? "Continuar fila" : "Iniciar fila";
    $("wa-fila-pausar").disabled = !ativa;
    $("wa-fila-cancelar-pendentes").disabled = c.pendente === 0;
    mostrar("wa-fila-linha-confirmo", !!(estado && !estado.simulado));
    const ativoNoCampo = (id) => document.activeElement && document.activeElement.id === id;
    if (!ativoNoCampo("wa-fila-intervalo")) $("wa-fila-intervalo").value = String(f.config.intervalo_s);
    if (!ativoNoCampo("wa-fila-limite")) $("wa-fila-limite").value = f.config.limite_diario;
    if (document.activeElement !== $("wa-fila-amanha")) $("wa-fila-amanha").checked = f.config.continuar_no_dia_seguinte;
    desenharItensFila();
  }

  function desenharItensFila() {
    const filtro = $("wa-fila-filtro").value;
    const itens = (fila?.itens || []).filter((i) =>
      filtro === "todas" ? true : filtro === "abertas" ? ["pendente", "enviando", "falhou"].includes(i.status) : i.status === filtro);
    $("wa-fila-lista").innerHTML = itens.length ? itens.map((i) => `
      <div class="checklist-item" style="display:block">
        <div style="display:flex;gap:8px;justify-content:space-between;align-items:flex-start">
          <div><strong>${esc(i.nome || i.numero)}</strong> · ${esc(i.numero)} · <em>${esc(ROTULOS_ITEM[i.status] || i.status)}</em>
            ${i.enviado_em ? ` · ${esc(new Date(i.enviado_em).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }))}` : ""}</div>
          <div>
            ${i.status === "pendente" ? `<button class="btn-sm" data-fila-acao="cancelar" data-id="${esc(i.id)}">Cancelar</button>` : ""}
            ${["falhou", "cancelado", "simulado"].includes(i.status) ? `<button class="btn-sm" data-fila-acao="repetir" data-id="${esc(i.id)}">Pôr na fila de novo</button>` : ""}
          </div>
        </div>
        <div class="campo-ajuda" style="margin:2px 0 0;white-space:pre-wrap">${esc(i.texto.length > 160 ? i.texto.slice(0, 160) + "…" : i.texto)}</div>
        ${i.erro ? `<div class="campo-ajuda" style="margin:2px 0 0;color:var(--rose)">${esc(i.erro)}</div>` : ""}
        ${i.aviso ? `<div class="campo-ajuda" style="margin:2px 0 0">${esc(i.aviso)}</div>` : ""}
      </div>`).join("") : `<div class="campo-ajuda">Nada para mostrar aqui.</div>`;
  }

  async function atualizarFila() {
    try {
      const r = await chamar("/fila");
      if (!r.ok) return;
      const assinatura = JSON.stringify(r.dados);
      if (assinatura === ultimaAssinaturaFila) return;      // nada mudou: não redesenha (não engole cliques nem perde a rolagem)
      ultimaAssinaturaFila = assinatura;
      fila = r.dados;
      desenharFila();
    } catch (e) { /* tenta no próximo ciclo */ }
  }

  function opcoesModelos(comComunicado) {
    return (comComunicado ? [`<option value="comunicado">Comunicado de matrícula (texto oficial do sistema)</option>`] : [])
      .concat(modelosFila.filter((m) => !comComunicado || m.texto.trim()).map((m) =>
        `<option value="${esc(m.id)}">${esc(m.nome + (m.padrao && m.personalizado ? " (ajustado)" : ""))}</option>`)).join("");
  }

  async function carregarModelosFila() {
    const r = await chamar("/fila/modelos");
    if (!r.ok) return;
    modelosFila = r.dados.modelos || [];
    const atual = $("wa-fila-modelo").value;
    $("wa-fila-modelo").innerHTML = opcoesModelos(false);
    if (atual) $("wa-fila-modelo").value = atual;
    const pmAtual = $("wa-fila-pm-modelo").value;
    $("wa-fila-pm-modelo").innerHTML = opcoesModelos(true);
    $("wa-fila-pm-modelo").value = pmAtual || (modelosFila.some((m) => m.id === "matricula_aprovada") ? "matricula_aprovada" : "comunicado");
    $("wa-fila-marcadores").textContent = "Marcadores que valem nos modelos: " + (r.dados.marcadores || []).map((m) => "$" + m).join(", ")
      + ". Na lista de alunos da pré-matrícula (próximo ano) eles são trocados pelos dados de cada aluno; numa mensagem avulsa, só valem $ESCOLA, $ANO, $PROXIMO_ANO_LETIVO e $DATA, e $ALUNO se você preencher o campo Nome.";
  }

  function iniciarFila() {
    $("wa-fila-modelo").addEventListener("change", () => {
      const m = modelosFila.find((x) => x.id === $("wa-fila-modelo").value);
      if (m) $("wa-fila-texto").value = m.texto;
    });
    $("wa-fila-filtro").addEventListener("change", desenharItensFila);

    $("wa-fila-iniciar").addEventListener("click", async () => {
      const real = estado && !estado.simulado;
      if (real && !$("wa-fila-confirmo").checked) { toast("Marque a confirmação para enviar de verdade."); return; }
      const r = await chamarFila("/iniciar", "POST", { confirmo: $("wa-fila-confirmo").checked });
      if (r) toast(r.mensagem_acao || "Fila iniciada.");
    });
    $("wa-fila-pausar").addEventListener("click", () => chamarFila("/pausar", "POST", {}));
    $("wa-fila-cancelar-pendentes").addEventListener("click", async () => {
      if (!confirm("Cancelar todas as mensagens pendentes? (Dá para pôr de volta na fila uma a uma.)")) return;
      const r = await chamarFila("/cancelar-pendentes", "POST", {});
      if (r) toast(r.mensagem_acao);
    });
    $("wa-fila-limpar").addEventListener("click", async () => {
      if (!confirm("Tirar da lista as mensagens já canceladas, simuladas, com falha e enviadas em dias anteriores? As pendentes e as enviadas hoje ficam.")) return;
      const r = await chamarFila("/limpar-historico", "POST", {});
      if (r) toast(r.mensagem_acao);
    });
    $("wa-fila-salvar-config").addEventListener("click", async () => {
      const r = await chamarFila("/config", "POST", {
        intervalo_s: $("wa-fila-intervalo").value, limite_diario: $("wa-fila-limite").value,
        continuar_no_dia_seguinte: $("wa-fila-amanha").checked });
      if (r) toast("Ajustes salvos.");
    });
    $("wa-fila-lista").addEventListener("click", async (ev) => {
      const b = ev.target.closest("[data-fila-acao]");
      if (b) await chamarFila(`/itens/${encodeURIComponent(b.dataset.id)}/${b.dataset.filaAcao}`, "POST", {});
    });

    function resumoAdicao(r) {
      const x = r.resultado || {};
      const partes = [`${x.adicionados || 0} na fila`];
      if (x.duplicados) partes.push(`${x.duplicados} já estavam (não repetem)`);
      if (x.sem_telefone?.length) partes.push(`sem telefone: ${x.sem_telefone.slice(0, 3).join("; ")}${x.sem_telefone.length > 3 ? "…" : ""}`);
      if (x.invalidos?.length) partes.push(`recusadas: ${x.invalidos.slice(0, 3).map((i) => `${i.nome} (${i.erro})`).join("; ")}`);
      toast(partes.join(" · "));
    }
    $("wa-fila-por").addEventListener("click", async () => {
      const r = await chamarFila("/itens", "POST", { itens: [{ numero: $("wa-fila-numero").value, nome: $("wa-fila-nome").value, texto: $("wa-fila-texto").value }] });
      if (!r) return;
      resumoAdicao(r);
      if (r.resultado.adicionados) { $("wa-fila-numero").value = ""; $("wa-fila-nome").value = ""; }
    });
    $("wa-fila-modelo-salvar").addEventListener("click", async () => {
      const atual = modelosFila.find((m) => m.id === $("wa-fila-modelo").value);
      const nome = prompt("Nome do modelo (se for o de um modelo existente, ele é atualizado):", atual && atual.id !== "livre" ? atual.nome : "");
      if (!nome) return;
      const existente = modelosFila.find((m) => m.nome.toLowerCase() === nome.trim().toLowerCase());
      const r = await chamar("/fila/modelos", "POST", { nome, texto: $("wa-fila-texto").value, id: existente?.id || "" });
      toast(r.ok ? "Modelo salvo." : (r.dados.erro || "Não foi possível salvar."));
      if (r.ok) { await carregarModelosFila(); $("wa-fila-modelo").value = r.dados.modelo.id; }
    });
    $("wa-fila-modelo-excluir").addEventListener("click", async () => {
      const id = $("wa-fila-modelo").value;
      if (!id || !confirm("Excluir este modelo? (Num modelo pronto ajustado, volta o texto original.)")) return;
      const r = await chamar(`/fila/modelos/${encodeURIComponent(id)}`, "DELETE");
      toast(r.ok ? (r.dados.acao === "restaurado" ? "Texto original restaurado." : "Modelo excluído.") : (r.dados.erro || "Não foi possível excluir."));
      if (r.ok) carregarModelosFila();
    });

    let pmAlunos = [];
    const ROTULO_SITUACAO = { matriculado: "matriculado", pendente: "aguardando vaga" };
    function pmVisiveis() {
      const turma = $("wa-fila-pm-turma").value;
      const ate = parseInt($("wa-fila-pm-ate").value, 10);
      return pmAlunos.filter((a) => {
        if (turma && a.turma !== turma) return false;
        if (Number.isFinite(ate) && ate > 0) {                       // com limite, quem não tem posição não dá para saber: fica fora
          const pos = parseInt(a.posicao, 10);
          if (!Number.isFinite(pos) || pos > ate) return false;
        }
        return true;
      });
    }
    function desenharPm(arquivo) {
      const marcados = new Set([...$("wa-fila-pm-lista").querySelectorAll("input:checked")].map((c) => c.dataset.pmId));
      const vis = pmVisiveis();
      $("wa-fila-pm-lista").innerHTML = vis.length ? vis.map((a) => `
        <label class="checklist-item"><input type="checkbox" data-pm-id="${esc(a.id)}" data-tem="${a.tem_telefone ? 1 : 0}"${a.tem_telefone ? "" : " disabled"}${marcados.has(a.id) && a.tem_telefone ? " checked" : ""}>
          ${esc(a.nome)} · ${esc(a.turma)}${a.posicao ? ` · ${esc(a.posicao)}º` : ""} · ${esc(ROTULO_SITUACAO[a.situacao] || a.situacao)}${a.tem_telefone ? "" : " · sem telefone"}</label>`).join("")
        : `<div class="campo-ajuda">Ninguém com esse filtro.</div>`;
      $("wa-fila-pm-info").textContent = `Arquivo ${arquivo || ""}: ${pmAlunos.length} alunos; ${vis.length} com o filtro atual `
        + `(${vis.filter((a) => a.tem_telefone).length} com telefone).`;
      mostrar("wa-fila-pm-todos", vis.length > 0);
      mostrar("wa-fila-pm-por", vis.length > 0);
    }
    let pmArquivo = "";
    $("wa-fila-pm-turma").addEventListener("change", () => desenharPm(pmArquivo));
    $("wa-fila-pm-ate").addEventListener("input", () => desenharPm(pmArquivo));
    $("wa-fila-pm-carregar").addEventListener("click", async () => {
      const r = await chamar("/fila/prematricula");
      if (!r.ok) { toast(r.dados.erro || "Não consegui ler a pré-matrícula."); return; }
      pmAlunos = r.dados.alunos || [];
      pmArquivo = r.dados.arquivo || "";
      const turmas = [...new Set(pmAlunos.map((a) => a.turma))].sort((a, b) => a.localeCompare(b, "pt-BR", { numeric: true }));
      const atual = $("wa-fila-pm-turma").value;
      $("wa-fila-pm-turma").innerHTML = `<option value="">Todas as turmas</option>`
        + turmas.map((tm) => `<option value="${esc(tm)}">${esc(tm)}</option>`).join("");
      if (turmas.includes(atual)) $("wa-fila-pm-turma").value = atual;
      $("wa-fila-pm-filtros").hidden = false;
      desenharPm(pmArquivo);
    });
    $("wa-fila-pm-todos").addEventListener("click", () =>
      $("wa-fila-pm-lista").querySelectorAll("input[data-tem='1']").forEach((c) => { c.checked = true; }));
    $("wa-fila-pm-por").addEventListener("click", async () => {
      const ids = [...$("wa-fila-pm-lista").querySelectorAll("input:checked")].map((c) => c.dataset.pmId);
      if (!ids.length) { toast("Marque pelo menos um aluno."); return; }
      const r = await chamarFila("/da-prematricula", "POST", { ids, modelo_id: $("wa-fila-pm-modelo").value });
      if (r) { resumoAdicao(r); $("wa-fila-pm-lista").querySelectorAll("input:checked").forEach((c) => { c.checked = false; }); }
    });
    carregarModelosFila();
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("sec-whatsapp")) return;

    iniciarFila();

    $("wa-usar-gateway").addEventListener("click", () => acao("/provedor", { provedor: "blake" }));
    $("wa-usar-whatsplay").addEventListener("click", () => acao("/provedor", { provedor: "whatsplay" }));
    document.querySelectorAll("[data-wa-modo]").forEach((b) =>
      b.addEventListener("click", () => acao("/provedor", { provedor: b.dataset.waModo })));

    $("wa-conectar").addEventListener("click", async () => {
      let r = await chamar("/conectar", "POST", {});
      if (r.status === 409 && r.dados.precisa_confirmar) {
        if (!confirm(r.dados.mensagem)) return;
        r = await chamar("/conectar", "POST", { forcar: true });
      }
      toast(r.dados.mensagem || r.dados.erro || "Pedido enviado.");
      atualizar();
    });

    $("wa-verificar").addEventListener("click", () =>
      acao("/verificar", { numero: $("wa-numero-verificar").value }));

    $("wa-enviar").addEventListener("click", async () => {
      const btn = $("wa-enviar");
      const real = estado && !estado.simulado;
      if (real && !$("wa-confirmo").checked) { toast("Marque a confirmação para enviar de verdade."); return; }
      btn.disabled = true;
      try {
        await acao("/teste", { numero: $("wa-numero").value, texto: $("wa-texto").value, confirmo: $("wa-confirmo").checked });
      } finally { btn.disabled = false; }
    });

    $("wa-alternar-envio").addEventListener("click", async () => {
      const ativar = !(estado && estado.envio_real);
      if (ativar && !confirm("Permitir que o sistema envie mensagens de verdade pelo WhatsApp conectado?")) return;
      await acao("/envio-real", { ativo: ativar, confirmo: ativar });
    });

    $("wa-webhook-registrar").addEventListener("click", () => acao("/webhooks", {}, atualizarWebhook));
    $("wa-webhook-remover").addEventListener("click", async () => {
      const r = await chamar("/webhooks", "DELETE");
      toast(r.dados.mensagem || r.dados.erro || "Feito.");
      atualizarWebhook();
    });

    $("wa-desconectar").addEventListener("click", () => {
      const whatsplay = estado && estado.provedor === "whatsplay";
      const aviso = whatsplay ? "Fechar o WhatsApp neste computador? O vínculo com o celular continua."
        : "Desconectar este número? Para vincular de novo pode ser preciso zerar o vínculo (docs/WHATSAPP.md).";
      if (confirm(aviso)) acao("/desconectar", {});
    });

    const cmd = $("wa-cmd");
    cmd.addEventListener("click", () => { navigator.clipboard?.writeText(cmd.textContent); toast("Comando copiado."); });
  });
})();
