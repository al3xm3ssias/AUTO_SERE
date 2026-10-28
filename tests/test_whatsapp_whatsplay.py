"""WhatsApp sem Docker — provedor `whatsplay` (WhatsApp Web via Playwright).

Unitários com sessão falsa + um teste com a biblioteca e um Chromium REAIS contra um WhatsApp Web de
mentira servido localmente (seletores copiados do código da whatsplay 2.6.1). Esse teste pula sozinho
se a biblioteca ou o Chromium não estiverem disponíveis. Nada acessa a internet nem o WhatsApp real.
"""
import asyncio
import logging
import socket
import threading
import time
from pathlib import Path

import pytest

from src.servicos.whatsapp.base import EnvioNaoAutorizadoError
from src.servicos.whatsapp.gerenciador import GerenciadorWhatsApp
from src.servicos.whatsapp.monitor import Foto, Situacao
from src.servicos.whatsapp.provedor_whatsplay import (ProvedorWhatsplay, SessaoWhatsplay, _MascararNumeros,
                                                      criar_provedor_whatsplay, proteger_log_da_biblioteca)
from src.web.api import whatsapp as wa_mod
from src.web.app import create_app


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    for k in ("WHATSAPP_ENVIO_REAL", "WHATSAPP_PROVEDOR", "WHATSAPP_WHATSPLAY_HEADLESS", "WHATSAPP_WHATSPLAY_PERFIL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "0")
    monkeypatch.delenv("WHATSAPP_ENVIO_REAL")


# ───────────────────────────── fakes ─────────────────────────────
class ClienteFalso:
    def __init__(self, retorno=True):
        self.retorno, self.chamadas = retorno, []

    async def send_message(self, alvo, texto, open_via_url=False):
        self.chamadas.append(("msg", alvo, texto, open_via_url))
        return self.retorno

    async def send_file(self, alvo, caminho, open_via_url=False):
        self.chamadas.append(("arq", alvo, Path(caminho).name, Path(caminho).read_bytes(), open_via_url))
        return self.retorno


class SessaoFalsa:
    def __init__(self, situacao=Situacao.CONECTADO, retorno=True, erro=""):
        self.situacao, self.cliente, self._erro, self._erro_no_envio = situacao, ClienteFalso(retorno), "", erro
        self.iniciada = self.parada = 0
        self.png = None

    def foto(self): return Foto(self.situacao, texto="")
    def qr_png(self): return self.png
    def ultimo_erro(self): return self._erro
    def limpar_erro(self): self._erro = ""
    def iniciar(self):
        from src.servicos.whatsapp.base import ResultadoAcao
        self.iniciada += 1
        return ResultadoAcao(True, "Abrindo.")
    def parar(self, timeout=0): self.parada += 1
    def executar(self, fazer, timeout=0):
        self._erro = self._erro_no_envio                    # a biblioteca emite on_error DURANTE o envio
        return asyncio.run(fazer(self.cliente))


def prov(sessao=None, **kw):
    s = sessao or SessaoFalsa()
    return ProvedorWhatsplay(s, intervalo_min_s=kw.pop("intervalo_min_s", 0), **kw), s


# ───────────────────────────── provedor ─────────────────────────────
def test_estado_traduz_cada_situacao():
    esperado = {Situacao.PARADO: False, Situacao.INICIANDO: False, Situacao.AGUARDANDO_QR: False,
                Situacao.CONECTADO: True, Situacao.DESCONECTADO: False}
    for sit, conectado in esperado.items():
        p, _ = prov(SessaoFalsa(sit))
        e = p.estado()
        assert (e.conectado, e.situacao) == (conectado, sit) and e.detalhe


def test_enviar_exige_autorizacao_e_nao_toca_na_sessao():
    p, s = prov()
    with pytest.raises(EnvioNaoAutorizadoError):
        p.enviar("42999998888", "oi")
    assert s.cliente.chamadas == []


def test_enviar_vai_por_numero_via_url_nunca_por_nome(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, s = prov()
    r = p.enviar("(42) 99999-8888", "Olá")
    assert r.ok and not r.simulado and r.id_mensagem is None
    assert s.cliente.chamadas == [("msg", "5542999998888", "Olá", True)]          # open_via_url=True e só dígitos


def test_enviar_recusa_numero_invalido_vazio_e_desconectado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, s = prov()
    with pytest.raises(ValueError):
        p.enviar("123", "oi")
    assert p.enviar("42999998888", "  ").erro == "Mensagem vazia."
    p2, s2 = prov(SessaoFalsa(Situacao.PARADO))
    assert "não está conectado" in p2.enviar("42999998888", "oi").erro and s2.cliente.chamadas == []


def test_falha_distingue_numero_invalido_de_envio_nao_confirmado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, _ = prov(SessaoFalsa(retorno=False, erro="Could not open chat: 5542999998888"))
    assert "não abriu a conversa" in p.enviar("42999998888", "oi").erro
    p, _ = prov(SessaoFalsa(retorno=False))
    erro = p.enviar("42999998888", "oi").erro
    assert "confira no WhatsApp antes de reenviar" in erro


def test_excecao_na_sessao_vira_falha_e_nao_derruba(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, s = prov()
    s.executar = lambda fazer, timeout=0: (_ for _ in ()).throw(TimeoutError("lento"))
    r = p.enviar("42999998888", "oi")
    assert not r.ok and "TimeoutError" in r.erro


def test_intervalo_minimo_entre_envios(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    agora, dormidos = [100.0], []
    p, _ = prov(intervalo_min_s=3.0, relogio=lambda: agora[0], dormir=dormidos.append)
    p.enviar("42999998888", "a")
    agora[0] = 101.0
    p.enviar("42999998888", "b")
    assert dormidos and 1.9 < dormidos[0] <= 2.0                                    # faltavam 2 s dos 3
    agora[0] = 200.0
    dormidos.clear()
    p.enviar("42999998888", "c")
    assert dormidos == []


def test_midia_vai_como_documento_sem_legenda_e_sanitiza_nome(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, s = prov()
    assert "legenda" in p.enviar_midia("42999998888", "document", b"x", nome_arquivo="a.pdf", legenda="oi").erro
    assert "vazio" in p.enviar_midia("42999998888", "document", b"", nome_arquivo="a.pdf").erro
    assert p.enviar_midia("42999998888", "document", b"%PDF", nome_arquivo="../../etc/te<r>mo.pdf").ok
    tipo, alvo, nome, conteudo, via_url = s.cliente.chamadas[-1]
    assert (tipo, alvo, conteudo, via_url) == ("arq", "5542999998888", b"%PDF", True)
    assert "/" not in nome and "<" not in nome and nome.endswith(".pdf")


def test_sair_fecha_o_navegador_sem_prometer_desvincular():
    p, s = prov()
    r = p.sair()
    assert r.ok and s.parada == 1 and "vínculo com o celular continua" in r.detalhe


# ───────────────────────────── log: número nunca em claro ─────────────────────────────
def test_filtro_mascara_numeros_longos(capsys):
    proteger_log_da_biblioteca()
    log = logging.getLogger("whatsplay.chat_manager")
    nivel = logging.getLogger("whatsplay").level
    logging.getLogger("whatsplay").setLevel(logging.INFO)
    try:
        log.info("Sending message to %r", "5542999998888")
        log.warning("Message to %r sent but not confirmed by server", "554299998888")
        log.info("tempo 2.5s e 12 itens")
    finally:
        logging.getLogger("whatsplay").setLevel(nivel)
    saida = capsys.readouterr().out
    assert "5542999998888" not in saida and "554299998888" not in saida
    assert "***88" in saida and "tempo 2.5s e 12 itens" in saida


def test_proteger_log_e_idempotente_e_silencia_info():
    proteger_log_da_biblioteca(); proteger_log_da_biblioteca()
    raiz = logging.getLogger("whatsplay")
    assert raiz.level == logging.WARNING
    assert all(sum(isinstance(f, _MascararNumeros) for f in h.filters) <= 1 for h in raiz.handlers)


# ───────────────────────────── whatsplay real: blindagens ─────────────────────────────
whatsplay = pytest.importorskip("whatsplay")


def test_cliente_pode_ser_criado_fora_da_thread_principal_e_servidor_de_qr_fica_desligado(tmp_path):
    from src.servicos.whatsapp.provedor_whatsplay import fabricar_cliente
    resultado = {}

    def criar():
        try:
            resultado["cliente"] = fabricar_cliente(tmp_path / "perfil", headless=True)
        except Exception as exc:                                                    # ValueError do signal.signal, antes da blindagem
            resultado["erro"] = repr(exc)
    t = threading.Thread(target=criar); t.start(); t.join(10)
    assert "erro" not in resultado, resultado.get("erro")
    from whatsplay import state_manager, utils
    for modulo in (state_manager, utils):
        assert modulo.show_qr_window() is None                                      # no-op: não abre servidor 0.0.0.0:8000
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", 8000), timeout=0.5).close()


# ───────────────────────────── gerenciador ─────────────────────────────
def gerenciador(sessao):
    prov_, _ = prov(sessao)
    return GerenciadorWhatsApp(prov_, None, "")


def test_gerenciador_conecta_so_quando_faz_sentido():
    s = SessaoFalsa(Situacao.PARADO)
    g = gerenciador(s)
    assert g.tem_sessao and not g.tem_gateway and not g.tem_webhook
    assert g.conectar()["ok"] and s.iniciada == 1
    for sit in (Situacao.CONECTADO, Situacao.INICIANDO, Situacao.AGUARDANDO_QR):
        s2 = SessaoFalsa(sit)
        r = gerenciador(s2).conectar()
        assert s2.iniciada == 0, sit                                                # não reabre o navegador à toa
    assert not gerenciador(SessaoFalsa(Situacao.CONECTADO)).conectar()["ok"]
    assert "gateway Docker" in gerenciador(s).verificar()["mensagem"]


def test_gerenciador_expoe_qr_png_e_id():
    s = SessaoFalsa(Situacao.AGUARDANDO_QR)
    g = gerenciador(s)
    assert g.qr_imagem() is None and g.qr_id() == ""
    s.png = b"\x89PNG\r\n\x1a\nxxxx"
    mime, dados = g.qr_imagem()
    assert mime == "image/png" and dados == s.png and len(g.qr_id()) == 12


# ───────────────────────────── rotas ─────────────────────────────
@pytest.fixture()
def cli(monkeypatch):
    gravados = []
    monkeypatch.setattr(wa_mod, "_persistir_env", lambda v: gravados.append(dict(v)))
    monkeypatch.setattr(wa_mod, "_ultimo_teste", 0.0)
    monkeypatch.setattr(wa_mod, "reiniciar_gerenciador", lambda: None)
    app = create_app(); app.testing = True
    return app.test_client(), gravados


def test_rotas_com_whatsplay(cli, monkeypatch):
    c, gravados = cli
    s = SessaoFalsa(Situacao.AGUARDANDO_QR)
    s.png = b"\x89PNG\r\n\x1a\n1234"
    ger = gerenciador(s)
    monkeypatch.setattr(wa_mod, "obter_gerenciador", lambda: ger)
    j = c.get("/web/api/whatsapp/status").get_json()
    assert (j["provedor"], j["tem_sessao"], j["tem_webhook"], j["situacao"]) == ("whatsplay", True, False, "aguardando_qr")
    assert j["qr_id"] and "PNG" not in str(j)
    r = c.get("/web/api/whatsapp/qr")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.headers["Cache-Control"] == "no-store"
    s.png = None
    assert c.get("/web/api/whatsapp/qr").status_code == 404
    assert c.get("/web/api/whatsapp/webhooks").status_code == 400                   # webhook só existe no gateway Docker
    assert c.post("/web/api/whatsapp/provedor", json={"provedor": "whatsplay"}).status_code == 200
    assert gravados[-1] == {"WHATSAPP_PROVEDOR": "whatsplay"}
    assert c.post("/web/api/whatsapp/desconectar").status_code == 200 and s.parada == 1


# ───────────────────────────── Chromium + whatsplay REAIS (WhatsApp Web de mentira) ─────────────────────────────
QR_HTML = """<canvas id=c aria-label="Scan this QR code to link a device!" width=120 height=120></canvas>
<script>const x=document.getElementById('c').getContext('2d');x.fillStyle='#000';x.fillRect(10,10,100,100);x.fillStyle='#fff';x.fillRect(30,30,60,60)</script>"""
LOGADO_HTML = """<span data-testid="wa-wordmark" style="display:inline-block;width:20px;height:20px">wa</span>
<div data-testid="chat-list" style="height:60px">chats</div>"""
CONVERSA_HTML = """<div id="box" contenteditable="true" role="textbox" style="height:30px;border:1px solid #000"></div><div id="msgs"></div>
<script>document.getElementById('box').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();
const b=document.getElementById('box');window.__enviadas=(window.__enviadas||[]);window.__enviadas.push(b.innerText);b.innerText='';
const d=document.createElement('div');d.setAttribute('data-testid','conv-msg-1');
d.innerHTML='<span aria-label="Sent" style="display:inline-block;width:10px;height:10px">ok</span>';document.getElementById('msgs').appendChild(d)}})</script>"""
INVALIDO_HTML = "<div>Phone number shared via url is invalid.</div>"


class WhatsAppDeMentira:
    def __init__(self):
        self.estado, self.visitas = "qr", []

    async def preparar(self, context):
        async def rota(route):
            url = route.request.url
            self.visitas.append(url)
            corpo = "<html><body>"
            if "/send?phone=" in url:
                corpo += LOGADO_HTML + (INVALIDO_HTML if url.endswith("0000") else CONVERSA_HTML)
            else:
                corpo += QR_HTML if self.estado == "qr" else LOGADO_HTML
            await route.fulfill(status=200, content_type="text/html", body=corpo + "</body></html>")
        await context.route("https://web.whatsapp.com/**", rota)


def _chromium_disponivel() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


def _esperar(cond, limite=40.0):
    t0 = time.time()
    while time.time() - t0 < limite:
        if cond():
            return True
        time.sleep(0.25)
    return False


@pytest.mark.skipif(not _chromium_disponivel(), reason="Chromium do Playwright indisponível")
def test_ciclo_completo_com_whatsplay_e_chromium_reais(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    mock = WhatsAppDeMentira()
    p = criar_provedor_whatsplay(tmp_path / "perfil", headless=True, preparar_contexto=mock.preparar)
    p._intervalo = 0
    sit = lambda: p.estado().situacao
    try:
        assert sit() == Situacao.PARADO
        assert p.iniciar_sessao().ok
        assert _esperar(lambda: sit() == Situacao.AGUARDANDO_QR), sit()
        assert _esperar(lambda: p.qr_png() is not None), "o PNG do QR não chegou"   # a captura vem logo depois do estado
        assert p.qr_png()[:8] == b"\x89PNG\r\n\x1a\n"                              # QR chega como imagem PNG
        with pytest.raises(OSError):                                                # servidor de QR da biblioteca desligado
            socket.create_connection(("127.0.0.1", 8000), timeout=0.5).close()

        mock.estado = "logado"
        p.sessao.executar(lambda c: c._page.reload())
        assert _esperar(lambda: sit() == Situacao.CONECTADO), sit()
        assert p.qr_png() is None

        r = p.enviar("(42) 99999-8888", "Olá, teste")
        assert r.ok, r.erro
        assert [v for v in mock.visitas if "/send?" in v] == ["https://web.whatsapp.com/send?phone=5542999998888"]
        assert p.sessao.executar(lambda c: c._page.evaluate("window.__enviadas")) == ["Olá, teste"]

        r = p.enviar("42 90000-0000", "x")                                          # a página diz "número inválido"
        assert not r.ok and "não abriu a conversa" in r.erro
    finally:
        p.sair()
    assert not p.sessao.ativa and sit() == Situacao.PARADO


@pytest.mark.skipif(not _chromium_disponivel(), reason="Chromium do Playwright indisponível")
def test_fechar_a_janela_do_navegador_volta_para_parado_e_permite_reabrir(tmp_path):
    mock = WhatsAppDeMentira()
    mock.estado = "logado"
    p = criar_provedor_whatsplay(tmp_path / "perfil", headless=True, preparar_contexto=mock.preparar)
    try:
        assert p.iniciar_sessao().ok
        assert _esperar(lambda: p.estado().situacao == Situacao.CONECTADO)
        p.sessao.executar(lambda c: c._page.close())                                # o usuário fecha a janela
        assert _esperar(lambda: p.estado().situacao == Situacao.PARADO, 40)
        assert "janela do navegador foi fechada" in p.estado().detalhe
        assert _esperar(lambda: not p.sessao.ativa, 30)
        assert p.iniciar_sessao().ok                                                # dá para abrir de novo
    finally:
        p.sair()
