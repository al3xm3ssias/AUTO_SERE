"""WhatsApp — gateway blakegt/whatsapp-web-api-rest: monitor SSE, provedor, eventos, rotas e tela.

Nada sai para a internet: o gateway é um servidor falso em 127.0.0.1 ou um objeto falso.
O comportamento do gateway real (SSE, `{}` sem sessão, DELETE 1-based) foi conferido à parte
rodando o gateway de verdade; estes testes travam esse contrato.
"""
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests

from src.servicos.whatsapp import eventos
from src.servicos.whatsapp.base import EnvioNaoAutorizadoError, EstadoConexao
from src.servicos.whatsapp.gateway_blake import MSG_NAO_CONFIRMOU, ProvedorBlake
from src.servicos.whatsapp.gerenciador import GerenciadorWhatsApp, qr_para_svg
from src.servicos.whatsapp.monitor import Foto, MonitorSessao, Situacao, fonte_sse_http
from src.web.api import whatsapp as wa_mod
from src.web.app import create_app

RAIZ = Path(__file__).resolve().parents[1]


def sse(qr="", text=""):
    return "data: " + json.dumps({"qr": qr, "text": text})


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    for k in ("WHATSAPP_ENVIO_REAL", "WHATSAPP_PROVEDOR", "WHATSAPP_API_URL", "WHATSAPP_WEBHOOK_TOKEN",
              "WHATSAPP_WEBHOOK_URL_BASE", "WHATSAPP_VALIDAR_NUMERO", "WHATSAPP_NUMERO_SONDA"):
        monkeypatch.delenv(k, raising=False)
    # `_gravar_env` mexe em os.environ: registrar o estado atual garante restauração no fim do teste.
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "0")
    monkeypatch.delenv("WHATSAPP_ENVIO_REAL")


# ───────────────────────────── fakes ─────────────────────────────
class Resp:
    def __init__(self, corpo=None, status=200, bruto=None):
        self.status_code = status
        self.content = bruto if bruto is not None else (b"" if corpo is None else json.dumps(corpo).encode())

    def json(self):
        return json.loads(self.content)


class HttpFalso:
    """Imita o gateway. `rotas[(METODO, caminho)]` = Resp, lista de Resp (consumida em ordem) ou exceção."""
    def __init__(self, rotas=None):
        self.rotas, self.chamadas = rotas or {}, []

    def _resp(self, metodo, url, **kw):
        caminho = "/" + url.split("//", 1)[1].split("/", 1)[1]
        self.chamadas.append((metodo, caminho, kw.get("json")))
        r = self.rotas.get((metodo, caminho))
        if isinstance(r, list):
            r = r.pop(0) if len(r) > 1 else r[0]
        if isinstance(r, Exception):
            raise r
        return r if r is not None else Resp({}, 200)

    def get(self, url, **kw): return self._resp("GET", url, **kw)
    def post(self, url, **kw): return self._resp("POST", url, **kw)
    def delete(self, url, **kw): return self._resp("DELETE", url, **kw)


JID = "5542999998888@s.whatsapp.net"
MSG_OK = {"key": {"remoteJid": JID, "fromMe": True, "id": "3EB0ABC"}, "status": 1}


def prov(rotas=None, **kw):
    http = HttpFalso(rotas)
    return ProvedorBlake("http://gw:8085", http=http, **kw), http


# ───────────────────────────── monitor ─────────────────────────────
def test_monitor_interpreta_eventos_do_gateway():
    m = MonitorSessao(lambda: iter(()))
    m._online = True
    m.processar_linha("id: 1")                       # ignorado
    m.processar_linha(": conectado")                 # ignorado
    m.processar_linha("data: {quebrado")             # ignorado
    assert m.foto().situacao == Situacao.DESCONHECIDO
    m.processar_linha(sse(qr="2@abc,def"))
    assert (m.foto().situacao, m.foto().qr) == (Situacao.AGUARDANDO_QR, "2@abc,def")
    m.processar_linha(sse(text="Connected to WhatsApp!"))
    assert (m.foto().situacao, m.foto().qr) == (Situacao.CONECTADO, "")
    m.processar_linha(sse(text="Reconnecting in 1000ms (attempt 1/4)"))
    assert m.foto().situacao == Situacao.RECONECTANDO
    m.processar_linha(sse(text="WebSocket Error (getaddrinfo ENOTFOUND)"))
    f = m.foto()
    assert f.situacao == Situacao.DESCONECTADO and "ENOTFOUND" in f.texto


def test_monitor_diz_verificando_ate_o_1o_resultado_e_depois_offline_e_nao_vaza_qr():
    m = MonitorSessao(lambda: iter(()))
    assert m.foto().situacao == Situacao.VERIFICANDO          # não acusa "offline" antes de tentar
    m._marcar_online(False)
    assert m.foto().situacao == Situacao.GATEWAY_OFFLINE
    m._online = True
    m.processar_linha(sse(qr="segredo"))
    m._online = False
    assert m.foto().qr == "" and m.foto().situacao == Situacao.GATEWAY_OFFLINE


def test_marcar_iniciando_nao_sobrescreve_evento_que_chegou_antes():
    t = [100.0]
    m = MonitorSessao(lambda: iter(()), relogio=lambda: t[0])
    m._online = True
    antes = m.foto().atualizado_em
    t[0] = 101.0
    m.processar_linha(sse(qr="2@x"))                 # o QR chegou durante o GET /
    m.marcar_iniciando(se_inalterado_desde=antes)
    assert m.foto().situacao == Situacao.AGUARDANDO_QR


def test_iniciando_expira_para_desconhecido():
    t = [0.0]
    m = MonitorSessao(lambda: iter(()), relogio=lambda: t[0])
    m._online = True
    m.marcar_iniciando()
    assert m.foto().situacao == Situacao.INICIANDO
    t[0] = 61.0
    assert m.foto().situacao == Situacao.DESCONHECIDO


def test_monitor_thread_reconecta_e_chama_ao_conectar():
    tentativas, sondas = [], []

    def fonte():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise requests.ConnectionError("gateway desligado")
        yield ": conectado"
        yield sse(text="Connected to WhatsApp!")
        time.sleep(0.2)                              # mantém o fluxo aberto um instante

    m = MonitorSessao(fonte, esperas=(0.01,), ao_conectar=lambda: sondas.append(1))
    m.iniciar()
    t0 = time.time()
    while time.time() - t0 < 3 and m.foto().situacao != Situacao.CONECTADO:
        time.sleep(0.02)
    m.parar()
    assert m.foto().situacao == Situacao.CONECTADO and m.foto().gateway_online
    assert len(tentativas) >= 2 and sondas == [1]


# ───────────────────────────── provedor: estado ─────────────────────────────
def test_estado_usa_o_monitor_e_traduz_cada_situacao():
    casos = {
        Situacao.CONECTADO: True, Situacao.AGUARDANDO_QR: False, Situacao.GATEWAY_OFFLINE: False,
        Situacao.DESCONHECIDO: False, Situacao.RECONECTANDO: False, Situacao.INICIANDO: False,
        Situacao.VERIFICANDO: False,
    }
    for sit, conectado in casos.items():
        mon = MonitorSessao(lambda: iter(()))
        mon._thread = type("T", (), {"is_alive": lambda s: True})()
        mon.foto = lambda sit=sit: Foto(sit, gateway_online=sit != Situacao.GATEWAY_OFFLINE)
        p, http = prov(monitor=mon)
        est = p.estado()
        assert (est.conectado, est.situacao) == (conectado, sit) and est.detalhe
        assert http.chamadas == []                   # com monitor, estado() não faz rede


def test_estado_sem_monitor_confirma_por_consulta():
    p, _ = prov({("GET", "/webhooks"): Resp([]), ("GET", "/number/5542900000000"): Resp(bruto=b"")})
    assert p.estado().conectado
    p, _ = prov({("GET", "/webhooks"): Resp([]), ("GET", "/number/5542900000000"): Resp({})})
    assert p.estado().situacao == Situacao.DESCONHECIDO
    p, _ = prov({("GET", "/webhooks"): requests.ConnectionError()})
    assert p.estado().situacao == Situacao.GATEWAY_OFFLINE


# ───────────────────────────── provedor: números e envio ─────────────────────────────
def test_consulta_de_numero_cobre_os_tres_formatos_do_gateway():
    p, _ = prov({("GET", "/number/5542999998888"): Resp({"jid": JID, "exists": True})})
    c = p.consultar_numero("(42) 99999-8888")
    assert (c.situacao, c.jid) == ("existe", JID)
    p, _ = prov({("GET", "/number/5542999998888"): Resp(bruto=b"")})            # conectado, sem WhatsApp
    assert p.consultar_numero("42999998888").situacao == "nao_existe"
    p, _ = prov({("GET", "/number/5542999998888"): Resp({})})                   # `{}` = erro engolido
    assert p.consultar_numero("42999998888").situacao == "indisponivel"
    p, _ = prov({("GET", "/number/5542999998888"): requests.ConnectionError()})
    assert p.consultar_numero("42999998888").situacao == "indisponivel"
    with pytest.raises(ValueError):
        p.consultar_numero("123")


def test_enviar_exige_autorizacao_e_nao_toca_a_rede():
    p, http = prov()
    with pytest.raises(EnvioNaoAutorizadoError):
        p.enviar("42999998888", "oi")
    assert http.chamadas == []


def test_enviar_usa_o_jid_do_whatsapp_e_confirma_pelo_id(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, http = prov({("GET", "/number/5542999998888"): Resp({"jid": "554299998888@s.whatsapp.net", "exists": True}),
                    ("POST", "/message"): Resp(MSG_OK, 201)})
    r = p.enviar("(42) 99999-8888", "Olá")
    assert r.ok and not r.simulado and r.id_mensagem == "3EB0ABC"
    assert http.chamadas[-1] == ("POST", "/message", {"chatId": "554299998888@s.whatsapp.net", "text": "Olá"})


def test_resposta_vazia_do_gateway_NAO_conta_como_enviado(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, _ = prov({("GET", "/number/5542999998888"): Resp({}), ("POST", "/message"): Resp({}, 201)})
    r = p.enviar("42999998888", "oi")
    assert not r.ok and r.erro == MSG_NAO_CONFIRMOU


def test_numero_sem_whatsapp_bloqueia_o_envio(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, http = prov({("GET", "/number/5542999998888"): Resp(bruto=b"")})
    r = p.enviar("42999998888", "oi")
    assert not r.ok and "não tem WhatsApp" in r.erro
    assert not any(c[0] == "POST" for c in http.chamadas)


def test_sem_validacao_vai_direto_e_mensagem_vazia_e_recusada(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, http = prov({("POST", "/message"): Resp(MSG_OK, 201)}, validar_numero=False)
    assert p.enviar("42999998888", "   ").erro == "Mensagem vazia."
    assert p.enviar("42999998888", "oi").ok
    assert http.chamadas == [("POST", "/message", {"chatId": "5542999998888@s.whatsapp.net", "text": "oi"})]


def test_erros_de_rede_viram_mensagem_amigavel(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, _ = prov({("POST", "/message"): requests.ConnectionError()}, validar_numero=False)
    assert "inacessível" in p.enviar("42999998888", "oi").erro
    p, _ = prov({("POST", "/message"): requests.Timeout()}, validar_numero=False)
    assert "demorou" in p.enviar("42999998888", "oi").erro


def test_midia_valida_antes_de_enviar(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    p, http = prov({("POST", "/message"): Resp(MSG_OK, 201)}, validar_numero=False)
    assert "Tipo de mídia" in p.enviar_midia("42999998888", "sticker", b"x").erro
    assert "nome do arquivo" in p.enviar_midia("42999998888", "document", b"x").erro
    assert "vazio" in p.enviar_midia("42999998888", "image", b"").erro
    assert "grande" in p.enviar_midia("42999998888", "image", b"0" * (19 * 1024 * 1024)).erro
    r = p.enviar_midia("42999998888", "document", b"%PDF", nome_arquivo="termo.pdf", legenda="Segue")
    assert r.ok
    midia = http.chamadas[-1][2]["media"]
    assert midia["type"] == "document" and midia["mimetype"] == "application/pdf" and midia["filename"] == "termo.pdf"
    assert midia["caption"] == "Segue" and midia["data"] == "JVBERg=="


# ───────────────────────────── provedor: administração ─────────────────────────────
def test_iniciar_sessao_marca_iniciando_so_se_deu_certo():
    mon = MonitorSessao(lambda: iter(()))
    mon._online = True
    p, _ = prov({("GET", "/"): Resp(bruto=b"<html>")}, monitor=mon)
    mon._thread = type("T", (), {"is_alive": lambda s: True})()
    assert p.iniciar_sessao().ok and mon.foto().situacao == Situacao.INICIANDO
    mon2 = MonitorSessao(lambda: iter(()))
    mon2._online = True
    p2, _ = prov({("GET", "/"): requests.ConnectionError()}, monitor=mon2)
    assert not p2.iniciar_sessao().ok and mon2.foto().situacao == Situacao.DESCONHECIDO


def test_webhook_remover_usa_indice_de_base_1_e_confere_depois():
    lista = ["http://a/1", "http://b/2", "http://c/3"]
    p, http = prov({("GET", "/webhooks"): [Resp(lista), Resp(["http://a/1", "http://c/3"])],
                    ("DELETE", "/webhooks/2"): Resp(bruto=b"")})
    assert p.webhook_remover("http://b/2").ok
    assert ("DELETE", "/webhooks/2", None) in http.chamadas
    p, _ = prov({("GET", "/webhooks"): [Resp(lista), Resp(lista)], ("DELETE", "/webhooks/1"): Resp(bruto=b"")})
    assert not p.webhook_remover("http://a/1").ok                                 # gateway não removeu


def test_webhook_registrar_e_idempotente_e_valida_url():
    p, http = prov({("GET", "/webhooks"): Resp(["http://x/1"])})
    assert p.webhook_registrar("http://x/1").ok
    assert not any(c[0] == "POST" for c in http.chamadas)
    assert not p.webhook_registrar("ftp://x").ok


# ───────────────────────────── servidor falso: SSE de verdade ─────────────────────────────
class GatewayFalso(BaseHTTPRequestHandler):
    eventos = []

    def log_message(self, *a): pass

    def do_GET(self):
        if self.path == "/sse":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for i, e in enumerate(self.eventos, 1):
                self.wfile.write(f"id: {i}\ndata: {json.dumps(e)}\n\n".encode())
                self.wfile.flush()
                time.sleep(0.05)
            time.sleep(0.5)
        elif self.path.startswith("/number/"):
            self.send_response(200); self.send_header("Content-Length", "0"); self.end_headers()
        else:
            self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"[]")


def test_monitor_contra_servidor_sse_real_em_localhost():
    GatewayFalso.eventos = [{"qr": "2@qr-um", "text": ""}, {"qr": "", "text": "Connected to WhatsApp!"}]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), GatewayFalso)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    mon = MonitorSessao(fonte_sse_http(url, timeout_leitura=5), esperas=(0.05,))
    mon.iniciar()
    vistos = set()
    t0 = time.time()
    while time.time() - t0 < 4 and Situacao.CONECTADO not in vistos:
        vistos.add(mon.foto().situacao)
        time.sleep(0.01)
    mon.parar()
    srv.shutdown()
    assert Situacao.CONECTADO in vistos


# ───────────────────────────── QR ─────────────────────────────
def test_qr_svg_tem_viewbox_e_nao_fixa_tamanho():
    svg = qr_para_svg("2@" + "a" * 120 + ",bbb,ccc")
    assert svg.startswith("<svg") and "viewBox" in svg and "<?xml" not in svg
    assert not re.search(r"\s(width|height)=", svg[:200])


# ───────────────────────────── eventos (módulos futuros) ─────────────────────────────
PAYLOAD = {"from": JID, "pushName": "Maria", "isMe": False, "type": "text", "message": "bom dia",
           "messageId": "ABC", "key": {"id": "ABC"}}


def test_interpretar_mensagem_individual_grupo_e_lixo():
    m = eventos.interpretar(PAYLOAD)
    assert (m.numero, m.texto, m.tipo, m.minha, m.em_grupo) == ("5542999998888", "bom dia", "text", False, False)
    g = eventos.interpretar({**PAYLOAD, "from": "1203630@g.us"})
    assert g.em_grupo and g.numero == ""
    assert eventos.interpretar({**PAYLOAD, "from": "9876@lid"}).numero == ""
    assert eventos.interpretar({"call": 1}) is None and eventos.interpretar("x") is None


def test_despachar_isola_tratador_com_erro_e_nao_loga_texto(caplog):
    vistos = []

    def ruim(msg): raise RuntimeError("falhou")
    def bom(msg): vistos.append(msg.texto)
    eventos.registrar_tratador(ruim); eventos.registrar_tratador(bom); eventos.registrar_tratador(bom)
    try:
        assert eventos.despachar(PAYLOAD) == 1 and vistos == ["bom dia"]
        assert "bom dia" not in caplog.text
        assert eventos.despachar({"call": 1}) == 0
    finally:
        eventos.remover_tratador(ruim); eventos.remover_tratador(bom)


# ───────────────────────────── rotas Flask ─────────────────────────────
class ProvFalso:
    nome = "blake"
    def __init__(self): self.enviados, self.sair_ok = [], True
    def estado(self): return EstadoConexao(True, "Conectado.", situacao=Situacao.CONECTADO)
    def enviar(self, numero, texto):
        from src.servicos.whatsapp.base import ResultadoEnvio
        self.enviados.append((numero, texto))
        return ResultadoEnvio(True, False, id_mensagem="ID1")


@pytest.fixture()
def cli(monkeypatch):
    gravados = []
    monkeypatch.setattr(wa_mod, "_persistir_env", lambda v: gravados.append(dict(v)))
    monkeypatch.setattr(wa_mod, "_ultimo_teste", 0.0)
    monkeypatch.setattr(wa_mod, "reiniciar_gerenciador", lambda: None)
    app = create_app()
    app.testing = True
    return app.test_client(), gravados


def com_gerenciador(monkeypatch, ger):
    monkeypatch.setattr(wa_mod, "obter_gerenciador", lambda: ger)


def gerenciador_blake(monkeypatch, situacao=Situacao.CONECTADO, qr=""):
    mon = MonitorSessao(lambda: iter(()))
    mon._online = True
    mon._situacao, mon._qr = situacao, qr
    p = ProvedorBlake("http://gw:8085", http=HttpFalso(), monitor=mon)
    mon._thread = type("T", (), {"is_alive": lambda s: True})()
    ger = GerenciadorWhatsApp(p, mon, "http://gw:8085")
    com_gerenciador(monkeypatch, ger)
    return ger


def test_status_simulado_por_padrao(cli):
    c, _ = cli
    j = c.get("/web/api/whatsapp/status").get_json()
    assert j["simulado"] and j["situacao"] == "simulado" and j["conectado"] and not j["envio_real"]


def test_status_com_qr_nao_expoe_o_qr_no_json_mas_serve_o_svg(cli, monkeypatch):
    c, _ = cli
    gerenciador_blake(monkeypatch, Situacao.AGUARDANDO_QR, qr="2@segredo," + "z" * 100)
    j = c.get("/web/api/whatsapp/status").get_json()
    assert j["situacao"] == "aguardando_qr" and j["qr_id"] and "segredo" not in json.dumps(j)
    r = c.get("/web/api/whatsapp/qr.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and r.headers["Cache-Control"] == "no-store"
    gerenciador_blake(monkeypatch, Situacao.CONECTADO)
    assert c.get("/web/api/whatsapp/qr.svg").status_code == 404


def test_conectar_pede_confirmacao_quando_estado_desconhecido(cli, monkeypatch):
    c, _ = cli
    ger = gerenciador_blake(monkeypatch, Situacao.DESCONHECIDO)
    r = c.post("/web/api/whatsapp/conectar", json={})
    assert r.status_code == 409 and r.get_json()["precisa_confirmar"]
    assert ger.provedor._http.chamadas == []                           # não abriu 2º socket
    ger.provedor._http.rotas[("GET", "/")] = Resp(bruto=b"<html>")
    assert c.post("/web/api/whatsapp/conectar", json={"forcar": True}).status_code == 200


def test_conectar_nao_mexe_em_sessao_ativa(cli, monkeypatch):
    c, _ = cli
    ger = gerenciador_blake(monkeypatch, Situacao.CONECTADO)
    r = c.post("/web/api/whatsapp/conectar", json={"forcar": True})
    assert r.status_code == 400 and ger.provedor._http.chamadas == []


def test_teste_exige_confirmacao_e_respeita_trava(cli, monkeypatch):
    c, _ = cli
    ger = gerenciador_blake(monkeypatch)
    ger.provedor = ProvedorBlake("http://gw:8085", http=HttpFalso({("POST", "/message"): Resp(MSG_OK, 201)}),
                                 monitor=ger.monitor, validar_numero=False)
    url = "/web/api/whatsapp/teste"
    assert c.post(url, json={"numero": "123"}).status_code == 400                   # número inválido
    assert c.post(url, json={"numero": "42999998888"}).get_json()["codigo_erro"] == "falta_confirmacao"
    r = c.post(url, json={"numero": "42999998888", "confirmo": True})
    assert r.status_code == 403 and r.get_json()["codigo_erro"] == "envio_real_bloqueado"
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    wa_mod._ultimo_teste = 0.0
    r = c.post(url, json={"numero": "42999998888", "confirmo": True})
    j = r.get_json()
    assert r.status_code == 200 and j["ok"] and j["destino"].endswith("88") and "42999998888" not in json.dumps(j)
    assert c.post(url, json={"numero": "42999998888", "confirmo": True}).status_code == 429   # anti duplo clique


def test_teste_falha_do_gateway_vira_502_sem_falso_sucesso(cli, monkeypatch):
    c, _ = cli
    ger = gerenciador_blake(monkeypatch)
    ger.provedor = ProvedorBlake("http://gw:8085", http=HttpFalso({("POST", "/message"): Resp({}, 201)}),
                                 monitor=ger.monitor, validar_numero=False)
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    r = c.post("/web/api/whatsapp/teste", json={"numero": "42999998888", "confirmo": True})
    assert r.status_code == 502 and not r.get_json()["ok"]


def test_teste_em_modo_simulado_nao_pede_confirmacao(cli):
    c, _ = cli
    r = c.post("/web/api/whatsapp/teste", json={"numero": "42999998888"})
    j = r.get_json()
    assert r.status_code == 200 and j["simulado"] and "Simulado" in j["mensagem"]


def test_envio_real_liga_e_desliga_com_confirmacao(cli, monkeypatch):
    c, gravados = cli
    assert c.post("/web/api/whatsapp/envio-real", json={"ativo": True}).status_code == 400
    assert gravados == []
    assert c.post("/web/api/whatsapp/envio-real", json={"ativo": True, "confirmo": True}).get_json()["envio_real"]
    assert gravados[-1] == {"WHATSAPP_ENVIO_REAL": "1"}
    assert not c.post("/web/api/whatsapp/envio-real", json={"ativo": False}).get_json()["envio_real"]


def test_provedor_valida_entrada(cli):
    c, gravados = cli
    assert c.post("/web/api/whatsapp/provedor", json={"provedor": "http"}).status_code == 400
    assert c.post("/web/api/whatsapp/provedor", json={"provedor": "blake", "url": "ftp://x"}).status_code == 400
    assert c.post("/web/api/whatsapp/provedor", json={"provedor": "blake", "url": "http://127.0.0.1:8085/"}).status_code == 200
    assert gravados[-1] == {"WHATSAPP_PROVEDOR": "blake", "WHATSAPP_API_URL": "http://127.0.0.1:8085"}


def test_webhook_so_aceita_com_token_e_despacha(cli, monkeypatch):
    c, gravados = cli
    recebido, pronto = [], threading.Event()
    def tratador(msg): recebido.append(msg.texto); pronto.set()
    eventos.registrar_tratador(tratador)
    try:
        assert c.post("/web/api/whatsapp/webhook?t=x", json=PAYLOAD).status_code == 403      # sem token configurado
        monkeypatch.setenv("WHATSAPP_WEBHOOK_TOKEN", "segredo123")
        assert c.post("/web/api/whatsapp/webhook?t=errado", json=PAYLOAD).status_code == 403
        assert c.post("/web/api/whatsapp/webhook", json=PAYLOAD).status_code == 403
        assert c.post("/web/api/whatsapp/webhook?t=segredo123", data="não é json").status_code == 400
        assert c.post("/web/api/whatsapp/webhook?t=segredo123", json=PAYLOAD).status_code == 200
        assert pronto.wait(2) and recebido == ["bom dia"]
    finally:
        eventos.remover_tratador(tratador)


def test_webhooks_registrar_cria_token_e_nao_devolve_url(cli, monkeypatch):
    c, gravados = cli
    ger = gerenciador_blake(monkeypatch)
    http = HttpFalso({("GET", "/webhooks"): Resp([]), ("POST", "/webhooks"): Resp({}, 201)})
    ger.provedor._http = http
    r = c.post("/web/api/whatsapp/webhooks")
    assert r.status_code == 200
    token = gravados[0]["WHATSAPP_WEBHOOK_TOKEN"]
    assert len(token) >= 20
    enviada = [x for x in http.chamadas if x[0] == "POST"][0][2]["url"]
    assert enviada.startswith("http://host.docker.internal:") and enviada.endswith(f"/web/api/whatsapp/webhook?t={token}")
    http.rotas[("GET", "/webhooks")] = Resp([enviada])
    j = c.get("/web/api/whatsapp/webhooks").get_json()
    assert j == {"registrado": True, "total_no_gateway": 1} and token not in json.dumps(j)


def test_wizard_whatsapp_so_conta_sessao_real(cli, monkeypatch):
    c, _ = cli
    assert c.get("/web/api/wizard/status").get_json()["whatsapp"] is False         # simulado não conta
    gerenciador_blake(monkeypatch, Situacao.CONECTADO)
    assert c.get("/web/api/wizard/status").get_json()["whatsapp"] is True
    assert c.post("/web/api/wizard/whatsapp/executar", json={}).status_code == 400  # já conectado: nada a iniciar


# ───────────────────────────── tela / arquivos ─────────────────────────────
def test_tela_whatsapp_esta_ligada_ao_menu_e_aos_ids_do_js():
    base = (RAIZ / "src/web/templates/base.html").read_text(encoding="utf-8")
    html = (RAIZ / "src/web/templates/whatsapp.html").read_text(encoding="utf-8")
    js = (RAIZ / "src/web/static/js/whatsapp.js").read_text(encoding="utf-8")
    app_js = (RAIZ / "src/web/static/js/app.js").read_text(encoding="utf-8")
    assert 'data-view="whatsapp"' in base and 'include "whatsapp.html"' in base and "js/whatsapp.js" in base
    assert 'id="sec-whatsapp"' in html and 'whatsapp: "WhatsApp"' in app_js
    ids_html = set(re.findall(r'id="([^"]+)"', html))
    assert len(re.findall(r'id="([^"]+)"', html)) == len(ids_html)                  # sem id duplicado
    usados = set(re.findall(r'\$\("([^"]+)"\)', js))
    assert usados <= ids_html, usados - ids_html


def test_compose_nao_expoe_a_porta_na_rede_e_usa_volume_nomeado():
    texto = (RAIZ / "docker/whatsapp/docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:8085:8085"' in texto
    assert not re.search(r'^\s*-\s*"?(0\.0\.0\.0:)?8085:8085', texto, re.M)
    assert "sessao_whatsapp:/app/auth_info" in texto and "blakegt/whatsapp-web-api-rest" in texto
