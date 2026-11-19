"""
Autorização do Google: abrir o link no navegador/perfil/conta certos e oferecer o link para COPIAR.
(src/comum/google_navegador.py, google_auth.py, configuracao.py e as rotas /web/api/google/autorizacao*.)
"""
from __future__ import annotations

import json

import pytest

from src.comum import configuracao, google_auth as ga, google_navegador as gn
from src.web.api import rotas
from src.web.app import create_app


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """Configuração e credenciais isoladas; nenhuma variável do ambiente real interfere."""
    monkeypatch.setattr(configuracao, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(configuracao, "ARQUIVO_CONFIG", tmp_path / "config_usuario.json")
    for v in ("GOOGLE_OAUTH_CONTA", "GOOGLE_OAUTH_NAVEGADOR", "GOOGLE_OAUTH_PERFIL", "GOOGLE_OAUTH_ABRIR_NAVEGADOR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("GOOGLE_API_CREDENTIALS", str(tmp_path / "cred.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    (tmp_path / "cred.json").write_text(json.dumps({"installed": {"client_id": "i", "client_secret": "S"}}), encoding="utf-8")
    monkeypatch.setattr(ga, "_pendente", None)
    return tmp_path


@pytest.fixture()
def perfis_chrome(tmp_path, monkeypatch):
    """Um 'User Data' do Chrome falso com dois perfis."""
    base = tmp_path / "chrome_dados"
    base.mkdir()
    (base / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Pessoal", "user_name": "pessoal@gmail.com"},
        "Profile 2": {"name": "Escola", "user_name": "Escola@Gmail.com"},
        "Profile 3": {"name": "Sem conta"}}}}), encoding="utf-8")
    monkeypatch.setattr(gn, "_pasta_dados_chromium", lambda nome: base if nome == "chrome" else None)
    return base


# ───────────────────────────── google_navegador ─────────────────────────────

def test_listar_perfis_e_achar_o_perfil_pelo_email(perfis_chrome):
    perfis = gn.listar_perfis("chrome")
    assert [p["pasta"] for p in perfis] == ["Default", "Profile 2", "Profile 3"]
    assert perfis[2]["email"] == ""
    assert gn.perfil_da_conta("chrome", "escola@gmail.com") == "Profile 2"       # sem diferenciar maiúsculas
    assert gn.perfil_da_conta("chrome", "outra@gmail.com") == ""
    assert gn.listar_perfis("firefox") == []


def test_listar_perfis_tolera_arquivo_ausente_ou_quebrado(tmp_path, monkeypatch):
    monkeypatch.setattr(gn, "_pasta_dados_chromium", lambda nome: tmp_path)
    assert gn.listar_perfis("chrome") == []
    (tmp_path / "Local State").write_text("não é json", encoding="utf-8")
    assert gn.listar_perfis("chrome") == []


def test_abrir_url_usa_o_perfil_logado_na_conta(perfis_chrome, monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: exe if n in ("chrome", str(exe)) else None)
    chamadas = []
    monkeypatch.setattr(gn, "_executar_destacado", lambda args: chamadas.append(args))
    abriu, desc = gn.abrir_url("https://accounts.google.com/o/oauth2/auth?x=1", navegador="chrome", conta="escola@gmail.com")
    assert abriu and "Chrome" in desc and "Escola" in desc
    assert chamadas == [[str(exe), "--profile-directory=Profile 2", "https://accounts.google.com/o/oauth2/auth?x=1"]]


def test_abrir_url_perfil_escolhido_vale_mais_que_a_conta(perfis_chrome, monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: exe if n == "chrome" else None)
    chamadas = []
    monkeypatch.setattr(gn, "_executar_destacado", lambda args: chamadas.append(args))
    gn.abrir_url("https://x.test/", navegador="chrome", perfil="Default", conta="escola@gmail.com")
    assert "--profile-directory=Default" in chamadas[0]


def test_abrir_url_sem_escolha_mas_com_conta_descobre_o_navegador(perfis_chrome, monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: exe if n == "chrome" else None)
    chamadas = []
    monkeypatch.setattr(gn, "_executar_destacado", lambda args: chamadas.append(args))
    assert gn.abrir_url("https://x.test/", conta="escola@gmail.com")[0]
    assert "--profile-directory=Profile 2" in chamadas[0]


def test_abrir_url_cai_no_navegador_padrao_se_o_escolhido_nao_existe(monkeypatch):
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: None)
    visto = []
    monkeypatch.setattr(gn.webbrowser, "open", lambda url, new=0: visto.append(url) or True)
    abriu, desc = gn.abrir_url("https://x.test/", navegador="chrome")
    assert abriu and visto == ["https://x.test/"] and "padrão" in desc


def test_abrir_url_recusa_o_que_nao_e_http(monkeypatch):
    monkeypatch.setattr(gn, "_executar_destacado", lambda a: pytest.fail("não devia abrir"))
    assert gn.abrir_url("file:///etc/passwd", navegador="chrome")[0] is False
    assert gn.abrir_url("--remote-debugging-port=1")[0] is False


# ───────────────────────────── preferências ─────────────────────────────

def test_preferencias_padrao_salvar_e_prioridade_do_ambiente(cfg, monkeypatch):
    assert configuracao.google_oauth_preferencias() == {"conta": "", "navegador": "", "perfil": "", "abrir": True}
    salvo = configuracao.definir_google_oauth(conta=" escola@gmail.com ", navegador="Chrome", perfil="Profile 2", abrir=False)
    assert salvo == {"conta": "escola@gmail.com", "navegador": "chrome", "perfil": "Profile 2", "abrir": False}
    monkeypatch.setenv("GOOGLE_OAUTH_CONTA", "outra@gmail.com")
    monkeypatch.setenv("GOOGLE_OAUTH_ABRIR_NAVEGADOR", "1")
    prefs = configuracao.google_oauth_preferencias()
    assert prefs["conta"] == "outra@gmail.com" and prefs["abrir"] is True and prefs["perfil"] == "Profile 2"


@pytest.mark.parametrize("campos", [{"conta": "isso não é e-mail"}, {"navegador": "/nao/existe/navegador.exe"},
                                    {"perfil": "../../x"}, {"perfil": 'a"b'}])
def test_preferencias_invalidas_sao_recusadas(cfg, campos):
    with pytest.raises(ValueError):
        configuracao.definir_google_oauth(**campos)


# ───────────────────────────── fluxo OAuth ─────────────────────────────

class FluxoFalso:
    """Imita InstalledAppFlow: run_local_server chama authorization_url como o de verdade, e o link carrega redirect_uri/state."""
    def __init__(self, vistos):
        self.vistos = vistos

    def authorization_url(self, **kw):
        self.vistos["kw_url"] = kw
        return "https://accounts.google.com/o/oauth2/auth?redirect_uri=http%3A%2F%2Flocalhost%3A5555%2F&state=ST123", "ST123"

    def run_local_server(self, **kw):
        self.vistos["kw_run"] = kw
        self.authorization_url(**{k: v for k, v in kw.items() if k == "login_hint"})
        self.vistos["pendente_durante"] = ga.autorizacao_pendente()
        from tests.test_google_sheets import CredFalsa
        return CredFalsa()


def _instalar_fluxo(monkeypatch, vistos):
    from google_auth_oauthlib.flow import InstalledAppFlow
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: FluxoFalso(vistos)))


def test_fluxo_abre_no_navegador_escolhido_manda_a_conta_e_publica_o_link(cfg, monkeypatch, capsys):
    configuracao.definir_google_oauth(conta="escola@gmail.com", navegador="chrome", perfil="Profile 2")
    vistos, aberturas = {}, []
    _instalar_fluxo(monkeypatch, vistos)
    monkeypatch.setattr(gn, "abrir_url", lambda url, **kw: aberturas.append((url, kw)) or (True, "Google Chrome, perfil “Escola”"))
    ga.obter_credenciais()

    assert aberturas[0][1] == {"navegador": "chrome", "perfil": "Profile 2", "conta": "escola@gmail.com"}
    assert vistos["kw_run"]["login_hint"] == "escola@gmail.com"           # o Google já abre com esta conta
    assert vistos["kw_run"]["open_browser"] is False                      # quem abre somos nós, no navegador certo
    pend = vistos["pendente_durante"]
    assert pend["url"].startswith("https://accounts.google.com/") and pend["aberto"] and pend["conta"] == "escola@gmail.com"
    assert not any(k.startswith("_") for k in pend)                       # o state não sai do módulo
    assert ga.autorizacao_pendente() is None                              # limpo depois de concluir
    assert "Link aberto em: Google Chrome" in capsys.readouterr().out


def test_fluxo_sem_abrir_sozinho_so_publica_o_link(cfg, monkeypatch):
    configuracao.definir_google_oauth(abrir=False)
    vistos = {}
    _instalar_fluxo(monkeypatch, vistos)
    monkeypatch.setattr(gn, "abrir_url", lambda *a, **k: pytest.fail("não devia abrir navegador"))
    ga.obter_credenciais()
    assert vistos["pendente_durante"]["aberto"] is False
    assert "login_hint" not in vistos["kw_run"]                           # sem conta configurada, nada é imposto


def test_pendente_e_limpo_mesmo_quando_a_autorizacao_falha(cfg, monkeypatch):
    from google_auth_oauthlib.flow import InstalledAppFlow

    class Falha(FluxoFalso):
        def run_local_server(self, **kw):
            self.authorization_url()
            raise RuntimeError("tempo esgotado")
    monkeypatch.setattr(InstalledAppFlow, "from_client_secrets_file", classmethod(lambda c, f, s: Falha({})))
    monkeypatch.setattr(gn, "abrir_url", lambda *a, **k: (True, "x"))
    with pytest.raises(ga.CredenciaisGoogleErro):
        ga.obter_credenciais()
    assert ga.autorizacao_pendente() is None


# ───────────────────────────── colar o endereço final ─────────────────────────────

def _pendente_falso(monkeypatch, redirect="http://localhost:5555/", state="ST123"):
    ga._registrar_pendente(f"https://accounts.google.com/o/oauth2/auth?redirect_uri={redirect}&state={state}",
                           {"conta": ""}, False, "")
    return ga


def test_colar_entrega_o_codigo_ao_servidor_local(cfg, monkeypatch):
    _pendente_falso(monkeypatch)
    import requests
    chamadas = []
    monkeypatch.setattr(requests, "get", lambda url, params=None, timeout=0: chamadas.append((url, params)))
    ga.concluir_colando("http://localhost:5555/?state=ST123&code=4%2FABC&scope=x")
    assert chamadas == [("http://localhost:5555/", {"state": "ST123", "code": "4/ABC", "scope": "x"})]


@pytest.mark.parametrize("colado, trecho", [
    ("http://localhost:5555/?state=ST123", "não tem o código"),
    ("http://localhost:5555/?state=OUTRO&code=1", "outra tentativa"),
    ("texto qualquer", "não tem o código"),
])
def test_colar_recusa_enderecos_errados(cfg, monkeypatch, colado, trecho):
    _pendente_falso(monkeypatch)
    with pytest.raises(ga.CredenciaisGoogleErro, match=trecho):
        ga.concluir_colando(colado)


def test_colar_nunca_chama_um_host_que_nao_seja_localhost(cfg, monkeypatch):
    _pendente_falso(monkeypatch, redirect="http://intranet.interna:5555/")
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("não devia fazer requisição"))
    with pytest.raises(ga.CredenciaisGoogleErro, match="endereço local"):
        ga.concluir_colando("http://x/?state=ST123&code=1")


def test_colar_sem_autorizacao_esperando(cfg):
    with pytest.raises(ga.CredenciaisGoogleErro, match="esperando"):
        ga.concluir_colando("http://localhost:1/?state=a&code=b")


# ───────────────────────────── rotas ─────────────────────────────

@pytest.fixture()
def cli(cfg, perfis_chrome, monkeypatch, tmp_path):
    monkeypatch.setattr(rotas, "_dados_dir", lambda: tmp_path)
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(gn, "localizar_navegador", lambda n: exe if n in ("chrome", str(exe)) else None)
    return create_app().test_client()


def test_rota_configuracao_lista_perfis_e_salva(cli):
    d = cli.get("/web/api/configuracoes/google-conta").get_json()
    assert [n["id"] for n in d["navegadores"]] == ["chrome"] and len(d["perfis"]["chrome"]) == 3
    r = cli.post("/web/api/configuracoes/google-conta", json={"conta": "escola@gmail.com", "navegador": "chrome", "abrir": True})
    assert r.status_code == 200 and r.get_json()["perfil_da_conta"] == {"chrome": "Profile 2"}
    assert cli.post("/web/api/configuracoes/google-conta", json={"conta": "lixo"}).status_code == 400


def test_rota_estado_da_autorizacao_e_abrir(cli, monkeypatch):
    assert cli.get("/web/api/google/autorizacao").get_json() == {"pendente": False}
    assert cli.post("/web/api/google/autorizacao/abrir").status_code == 400
    ga._registrar_pendente("https://accounts.google.com/o/oauth2/auth?redirect_uri=http://localhost:5/&state=S", {"conta": "a@b.co"}, False, "")
    estado = cli.get("/web/api/google/autorizacao").get_json()
    assert estado["pendente"] and estado["url"].startswith("https://accounts.google.com/") and estado["conta"] == "a@b.co"
    assert "_state" not in estado and "_redirect_uri" not in estado
    visto = []
    monkeypatch.setattr(gn, "abrir_url", lambda url, **kw: visto.append(url) or (True, "Google Chrome"))
    # o endereço NUNCA vem do cliente: mesmo mandando um, só abre o da tentativa atual
    assert cli.post("/web/api/google/autorizacao/abrir", json={"url": "https://malicioso.test/"}).status_code == 200
    assert visto == [estado["url"]]


def test_rota_testar_abertura(cli, monkeypatch):
    visto = []
    monkeypatch.setattr(gn, "_executar_destacado", lambda args: visto.append(args))
    r = cli.post("/web/api/configuracoes/google-conta/testar", json={"navegador": "chrome", "conta": "escola@gmail.com"})
    assert r.status_code == 200 and "--profile-directory=Profile 2" in visto[0] and visto[0][-1].startswith("https://myaccount.google.com")


# ───────────────────────────── servidor local de verdade (InstalledAppFlow) ─────────────────────────────

def test_colar_o_endereco_final_conclui_o_fluxo_real_do_oauthlib(cfg, monkeypatch):
    """Sem navegador nenhum: o link é publicado, o 'colar' entrega o código ao servidor local de verdade e o fluxo termina."""
    import threading
    import time
    from urllib.parse import parse_qs, urlparse

    from google_auth_oauthlib.flow import InstalledAppFlow
    from tests.test_google_sheets import CredFalsa

    recebido = {}
    monkeypatch.setattr(InstalledAppFlow, "fetch_token", lambda self, **kw: recebido.update(kw))
    monkeypatch.setattr(InstalledAppFlow, "credentials", property(lambda self: CredFalsa()))
    (cfg / "cred.json").write_text(json.dumps({"installed": {          # completo: o fluxo REAL exige estes campos
        "client_id": "i", "client_secret": "S", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    configuracao.definir_google_oauth(conta="escola@gmail.com", abrir=False)

    resultado = {}
    fio = threading.Thread(target=lambda: resultado.update(creds=ga.obter_credenciais()), daemon=True)
    fio.start()
    pend = None
    for _ in range(100):
        pend = ga.autorizacao_pendente()
        if pend:
            break
        time.sleep(0.05)
    assert pend and pend["aberto"] is False
    consulta = parse_qs(urlparse(pend["url"]).query)
    assert consulta["login_hint"] == ["escola@gmail.com"]                      # a conta chegou na URL de verdade
    state, redirect = consulta["state"][0], consulta["redirect_uri"][0]

    ga.concluir_colando(f"{redirect}?state={state}&code=CODIGO123&scope=x")    # o que o usuário colaria da barra do navegador
    fio.join(timeout=10)
    assert not fio.is_alive() and "creds" in resultado
    assert "code=CODIGO123" in recebido["authorization_response"]
    assert (cfg / "token.json").is_file() and ga.autorizacao_pendente() is None
