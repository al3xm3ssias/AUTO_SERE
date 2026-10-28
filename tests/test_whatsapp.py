"""WhatsApp: provedor simulado, gateway HTTP (servidor falso) e o teste seguro."""
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.servicos import whatsapp as wa  # noqa: E402
from src.servicos.whatsapp import teste as teste_cli  # noqa: E402

VARS = ("WHATSAPP_PROVEDOR", "WHATSAPP_API_URL", "WHATSAPP_API_KEY", "WHATSAPP_SESSAO", "WHATSAPP_ENVIO_REAL")


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    # Rede proibida em todos os testes: qualquer chamada real a requests falha o teste.
    def proibido(*a, **k):
        pytest.fail("os testes não podem acessar a rede")
    monkeypatch.setattr(requests, "get", proibido)
    monkeypatch.setattr(requests, "post", proibido)
    monkeypatch.setattr(requests.sessions.Session, "request", proibido)


class Resp:
    def __init__(self, status=200, corpo=None):
        self.status_code, self._c = status, corpo
        self.content = b"x" if corpo is not None else b""
    def json(self):
        if self._c is None:
            raise ValueError("sem json")
        return self._c


class HttpFalso:
    def __init__(self, get=None, post=None):
        self.chamadas, self._get, self._post = [], get, post
    def get(self, url, **k):
        self.chamadas.append(("GET", url, k))
        if isinstance(self._get, Exception):
            raise self._get
        return self._get
    def post(self, url, **k):
        self.chamadas.append(("POST", url, k))
        if isinstance(self._post, Exception):
            raise self._post
        return self._post


# ── números ──
@pytest.mark.parametrize("entrada,saida", [
    ("(42) 99999-8888", "5542999998888"), ("42 3222-1111", "554232221111"),
    ("+55 42 99999-8888", "5542999998888"), ("5542999998888", "5542999998888")])
def test_normalizar_numero(entrada, saida):
    assert wa.normalizar_numero(entrada) == saida


@pytest.mark.parametrize("ruim", ["", "123", "99999-8888", "004299999888877", "5500999998888", "abc"])
def test_numero_invalido(ruim):
    with pytest.raises(ValueError):
        wa.normalizar_numero(ruim)


def test_mascara_nao_revela_o_numero():
    m = wa.mascarar_numero("5542999998888")
    assert m.endswith("88") and "99999" not in m and "9999" not in m


# ── simulado ──
def test_simulado_nunca_usa_a_rede_e_registra():
    p = wa.ProvedorSimulado()
    assert p.estado().conectado and "Simulado" in p.estado().detalhe
    r = p.enviar("42 99999-8888", "oi")
    assert r.ok and r.simulado and p.enviadas == [("5542999998888", "oi")]
    assert not p.enviar("42 99999-8888", "  ").ok


def test_padrao_do_sistema_e_o_simulado():
    assert wa.criar_provedor().nome == "simulado"


def test_http_exige_configuracao_completa(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "http")
    with pytest.raises(wa.ConfiguracaoIncompletaError, match="WHATSAPP_API_URL, WHATSAPP_API_KEY"):
        wa.criar_provedor()
    monkeypatch.setenv("WHATSAPP_API_URL", "http://localhost:3000/")
    monkeypatch.setenv("WHATSAPP_API_KEY", "k")
    p = wa.criar_provedor()
    assert p.nome == "http" and p.url_base == "http://localhost:3000"


def test_provedor_desconhecido(monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "pombo")
    with pytest.raises(wa.ConfiguracaoIncompletaError, match="desconhecido"):
        wa.criar_provedor()


# ── gateway http ──
def test_estado_conectado_e_nao_conectado():
    ok = wa.ProvedorHttp("http://gw", "chave", http=HttpFalso(get=Resp(200, {"success": True, "state": "CONNECTED"})))
    assert ok.estado().conectado
    qr = wa.ProvedorHttp("http://gw", "chave", http=HttpFalso(get=Resp(200, {"success": True, "state": "SCAN_QR_CODE"})))
    e = qr.estado()
    assert not e.conectado and "QR" in e.detalhe


def test_estado_usa_somente_get_com_a_chave():
    http = HttpFalso(get=Resp(200, {"success": True, "state": "CONNECTED"}))
    wa.ProvedorHttp("http://gw", "segredo", sessao="escola", http=http).estado()
    assert [(m, u) for m, u, _ in http.chamadas] == [("GET", "http://gw/session/status/escola")]
    assert http.chamadas[0][2]["headers"]["x-api-key"] == "segredo"


@pytest.mark.parametrize("resp,trecho", [
    (requests.ConnectionError("x"), "inacessível"), (Resp(401, {}), "chave"),
    (Resp(500, {}), "erro 500"), (Resp(200, None), "não é JSON")])
def test_estado_falhas_viram_mensagem_clara(resp, trecho):
    e = wa.ProvedorHttp("http://gw", "k", http=HttpFalso(get=resp)).estado()
    assert not e.conectado and trecho in e.detalhe


def test_envio_real_bloqueado_sem_autorizacao_e_sem_chamar_a_rede():
    http = HttpFalso(post=Resp(200, {"success": True}))
    with pytest.raises(wa.EnvioNaoAutorizadoError, match="WHATSAPP_ENVIO_REAL"):
        wa.ProvedorHttp("http://gw", "k", http=http).enviar("42 99999-8888", "oi")
    assert http.chamadas == []                                    # nem tentou


def test_envio_real_autorizado_monta_a_chamada_certa(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    http = HttpFalso(post=Resp(200, {"success": True, "message": {"id": {"_serialized": "ABC123"}}}))
    r = wa.ProvedorHttp("http://gw", "k", sessao="escola", http=http).enviar("(42) 99999-8888", "Olá")
    assert r.ok and not r.simulado and r.id_mensagem == "ABC123"
    metodo, url, kw = http.chamadas[0]
    assert (metodo, url) == ("POST", "http://gw/client/sendMessage/escola")
    assert kw["json"] == {"chatId": "5542999998888@c.us", "contentType": "string", "content": "Olá"}


def test_envio_real_trata_erros(monkeypatch):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    assert "rede" in wa.ProvedorHttp("http://gw", "k", http=HttpFalso(post=requests.ConnectionError("x"))).enviar("42 99999-8888", "oi").erro
    r = wa.ProvedorHttp("http://gw", "k", http=HttpFalso(post=Resp(400, {"success": False, "error": "sessão fechada"}))).enviar("42 99999-8888", "oi")
    assert not r.ok and r.erro == "sessão fechada"
    with pytest.raises(ValueError):
        wa.ProvedorHttp("http://gw", "k", http=HttpFalso()).enviar("123", "oi")


# ── o teste seguro (linha de comando) ──
def test_cli_padrao_nao_envia_nada_e_diz_isso(capsys):
    assert teste_cli.main([]) == 0
    saida = capsys.readouterr().out
    assert "Provedor configurado: simulado" in saida and "Nenhuma mensagem real foi enviada" in saida


def test_cli_com_gateway_configurado_faz_so_leitura(monkeypatch, capsys):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "http")
    monkeypatch.setenv("WHATSAPP_API_URL", "http://gw")
    monkeypatch.setenv("WHATSAPP_API_KEY", "segredo-da-chave")
    http = HttpFalso(get=Resp(200, {"success": True, "state": "CONNECTED"}), post=Resp(200, {"success": True}))
    assert teste_cli.main([], provedor=wa.ProvedorHttp("http://gw", "segredo-da-chave", http=http)) == 0
    assert [c[0] for c in http.chamadas] == ["GET"]               # nenhum POST
    saida = capsys.readouterr().out
    assert "CONECTADO" in saida and "segredo-da-chave" not in saida   # a chave nunca é impressa


def test_cli_gateway_desconectado_devolve_erro(monkeypatch, capsys):
    http = HttpFalso(get=Resp(200, {"success": True, "state": "SCAN_QR_CODE"}))
    assert teste_cli.main([], provedor=wa.ProvedorHttp("http://gw", "k", http=http)) == 1


def test_cli_sem_configuracao_do_gateway(monkeypatch, capsys):
    monkeypatch.setenv("WHATSAPP_PROVEDOR", "http")
    assert teste_cli.main([]) == 1
    assert "WHATSAPP_API_URL" in capsys.readouterr().err


@pytest.mark.parametrize("argv,env,trecho", [
    (["--enviar-para", "42999998888"], {}, "--confirmo-envio-real"),                       # falta a confirmação
    (["--enviar-para", "42999998888", "--confirmo-envio-real"], {}, "simulado"),            # provedor simulado
])
def test_cli_envio_real_recusado_sem_as_tres_travas(argv, env, trecho, capsys):
    assert teste_cli.main(argv) == 2
    assert trecho in capsys.readouterr().err


def test_cli_envio_real_recusado_sem_variavel_de_ambiente(capsys):
    http = HttpFalso(get=Resp(200, {"success": True, "state": "CONNECTED"}), post=Resp(200, {"success": True}))
    prov = wa.ProvedorHttp("http://gw", "k", http=http)
    assert teste_cli.main(["--enviar-para", "42999998888", "--confirmo-envio-real"], provedor=prov) == 2
    assert "WHATSAPP_ENVIO_REAL" in capsys.readouterr().err
    assert "POST" not in [c[0] for c in http.chamadas]


def test_cli_envio_real_com_as_tres_travas(monkeypatch, capsys):
    monkeypatch.setenv("WHATSAPP_ENVIO_REAL", "1")
    http = HttpFalso(get=Resp(200, {"success": True, "state": "CONNECTED"}), post=Resp(200, {"success": True}))
    prov = wa.ProvedorHttp("http://gw", "k", http=http)
    assert teste_cli.main(["--enviar-para", "42999998888", "--confirmo-envio-real"], provedor=prov) == 0
    assert [c[0] for c in http.chamadas] == ["GET", "POST"]
    saida = capsys.readouterr().out
    assert "enviada para" in saida and "999998888" not in saida     # número aparece só mascarado
