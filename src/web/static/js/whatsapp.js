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

  document.addEventListener("DOMContentLoaded", () => {
    if (!$("sec-whatsapp")) return;

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
